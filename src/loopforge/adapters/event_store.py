"""Bounded, session-local observations. These records never grant authority.

Eight 128 KiB segments retain up to 1 MiB per execution. The atomic index
records dropped segments and monotonic order; readers page retained events.
The human transcript remains a compatibility artifact, not the event store.
"""
from __future__ import annotations

import codecs
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from loopforge.engine.storage import DEFAULT_JSON_STORE

SEGMENT_BYTES = 131_072
MAX_SEGMENTS = 8
MAX_EVENT_BYTES = 24_576
MAX_PAGE_EVENTS = 500
INDEX_NAME = "agent-events-index.json"


def safe_path(root: Path, relative: str) -> Path | None:
    """Reject traversals and every symlink component, even inside the root."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return None
    candidate = root
    try:
        for part in path.parts:
            candidate = candidate / part
            if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                return None
        candidate.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return candidate


def _safe(value: object, limit: int = 6000) -> str:
    from loopforge.adapters.local_implementation_adapter import observable_stream_text
    return observable_stream_text(value, limit=limit)


def normalize_event(event: dict[str, Any], *, provenance: str = "native-json") -> tuple[dict[str, Any], ...]:
    """Allow-listed public native fields; no classifications from free prose."""
    from loopforge.adapters.local_implementation_adapter import adapter_event_lines
    output: list[dict[str, Any]] = []
    def add(kind: str, title: str, body: object = "", *, call_id: object = None,
            state: object = None, category: str = "", native_id: object = None,
            parent_id: object = None, payload: dict | None = None) -> None:
        status = {"in_progress": "running", "pending": "running", "error": "failed"}.get(str(state), str(state or "unknown"))
        if status not in {"running", "completed", "failed", "unknown"}:
            status = "unknown"
        value = {"schema_version": 1, "source": "harness", "provenance": provenance,
                 "kind": kind, "title": _safe(title, 200), "body": _safe(body),
                 "status": status, "category": category, "capture_state": "bounded"}
        for key, item in (("call_id", call_id), ("native_id", native_id), ("parent_id", parent_id),
                          ("occurred_at", event.get("timestamp"))):
            if isinstance(item, (str, int)) and not isinstance(item, bool):
                value[key] = _safe(str(item), 300)
        if payload is not None:
            value["rendered"] = "\n".join(adapter_event_lines(payload, {}))[:10000]
        output.append(value)
    def category(name: object) -> str:
        return {"Read": "read", "read": "read", "Glob": "search", "Grep": "search",
                "glob": "search", "grep": "search", "web_search": "search"}.get(str(name), "")
    hook = event.get("hook_event_name")
    if hook in {"PreToolUse", "PostToolUse", "PostToolUseFailure"}:
        name = event.get("tool_name") or "Tool"
        state = "running" if hook == "PreToolUse" else "failed" if hook == "PostToolUseFailure" else "completed"
        add("tool", str(name), event.get("tool_input") if state == "running" else event.get("tool_response") or event.get("error"),
            call_id=event.get("tool_use_id"), state=state, category=category(name))
    elif hook == "Stop" and event.get("last_assistant_message"):
        add("message", "Agent", event["last_assistant_message"])
    elif isinstance(event.get("part"), dict):
        part = event["part"]
        kind = part.get("type") or event.get("type")
        if kind in {"text", "reasoning"}:
            add("reasoning" if kind == "reasoning" else "message", "Reasoning" if kind == "reasoning" else "Agent",
                part.get("text"), native_id=part.get("id"), payload=event)
        elif kind in {"tool", "tool_use"}:
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            name = part.get("tool") or "Tool"
            add("tool", str(name), state, call_id=part.get("callID") or part.get("id"),
                state=state.get("status"), category=category(name), native_id=part.get("id"),
                parent_id=part.get("parentID"), payload=event)
    elif event.get("type") in {"assistant", "user"} and isinstance(event.get("message"), dict):
        message = event["message"]
        for block in message.get("content", []) if isinstance(message.get("content"), list) else []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            single = {**event, "message": {**message, "content": [block]}}
            if event["type"] == "assistant" and kind in {"text", "thinking"}:
                add("reasoning" if kind == "thinking" else "message", "Reasoning" if kind == "thinking" else "Agent",
                    block.get("thinking") if kind == "thinking" else block.get("text"), payload=single)
            elif event["type"] == "assistant" and kind == "tool_use":
                add("tool", str(block.get("name") or "Tool"), block.get("input"), call_id=block.get("id"),
                    state="running", category=category(block.get("name")), payload=single)
            elif kind == "tool_result":
                add("tool", "Tool", block.get("content"), call_id=block.get("tool_use_id"),
                    state="failed" if block.get("is_error") else "completed", payload=single)
    elif isinstance(event.get("item"), dict):
        item = event["item"]
        kind = item.get("type")
        native_id = item.get("id")
        if kind in {"agent_message", "reasoning", "todo_list", "file_change", "error"}:
            mapped = {"agent_message": "message", "todo_list": "plan", "file_change": "file_change", "reasoning": "reasoning", "error": "error"}[kind]
            add(mapped, {"message": "Agent", "plan": "Plan"}.get(mapped, mapped.title()),
                item.get("text") or item.get("items") or item.get("changes") or item.get("message"),
                native_id=native_id, state="failed" if kind == "error" else None, payload=event)
            if kind == "file_change" and isinstance(item.get("changes"), list):
                # Native structured paths only: never infer file changes from prose.
                # Keep the observed action as a declaration, not Git evidence.
                files = []
                for change in item["changes"][:100]:
                    if not isinstance(change, dict):
                        continue
                    raw = change.get("path")
                    if not isinstance(raw, str) or not raw or len(raw) > 1024:
                        continue
                    clean = _safe(raw, 1024)
                    normalized = clean.replace("\\", "/")
                    if (not normalized or normalized.startswith("/") or
                            any(part in {"..", "."} for part in normalized.split("/")) or
                            ":" in normalized.split("/")[0]):
                        continue
                    action = str(change.get("kind") or "").lower()
                    action = {"update": "modified", "add": "added",
                              "delete": "deleted", "move": "renamed"}.get(action, "unknown")
                    files.append({"path": normalized, "action": action})
                output[-1]["files"] = files
        elif kind in {"command_execution", "mcp_tool_call", "web_search"}:
            status = item.get("status")
            if item.get("error") or (isinstance(item.get("exit_code"), int) and item["exit_code"] != 0):
                status = "failed"
            elif not status:
                status = "completed" if event.get("type") == "item.completed" else "running" if event.get("type") == "item.started" else "unknown"
            title = "Shell" if kind == "command_execution" else str(item.get("tool") or "Search" if kind == "web_search" else item.get("tool") or "MCP")
            add("tool", title, item, call_id=item.get("call_id") or native_id, native_id=native_id,
                state=status, category="search" if kind == "web_search" else "", payload=event)
    elif event.get("type") == "event_msg" and isinstance(event.get("payload"), dict):
        payload = event["payload"]
        if payload.get("type") in {"agent_message", "agent_reasoning"}:
            reasoning = payload["type"] == "agent_reasoning"
            add("reasoning" if reasoning else "message", "Reasoning" if reasoning else "Agent", payload.get("message") or payload.get("text"))
    elif event.get("type") == "result" and event.get("result"):
        add("error" if event.get("is_error") else "message", "Agent", event["result"], payload=event)
    elif event.get("type") in {"error", "turn.failed"}:
        add("error", "Agent error", event.get("error") or event.get("message"), state="failed", payload=event)
    return tuple(output)


class EventStore:
    """One writer per observation session; errors cannot affect execution."""
    def __init__(self, directory: Path):
        self.directory = directory
        self.seen: list[str] = []

    def append(self, event: dict[str, Any]) -> None:
        try:
            index_path = safe_path(self.directory, INDEX_NAME)
            if index_path is None:
                return
            index = read_index(self.directory)
            segments = list(index.get("segments", []))
            order = int(index.get("next_order", 0))
            identity = event.get("native_id") or event.get("call_id")
            fingerprint = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
            if identity and fingerprint in self.seen:
                return
            record = {**event, "order": order, "event_id": f"event-{order:08d}"}
            data = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            if len(data) > MAX_EVENT_BYTES:
                record.pop("rendered", None)
                record["body"] = str(record.get("body", ""))[:2000]
                record["capture_state"] = "bounded"
                data = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            segment = segments[-1] if segments else {"name": f"agent-events-{order:08d}.jsonl", "first_order": order, "bytes": 0}
            if segment["bytes"] + len(data) > SEGMENT_BYTES:
                segment = {"name": f"agent-events-{order:08d}.jsonl", "first_order": order, "bytes": 0}
            if not segments or segment is not segments[-1]:
                segments.append(segment)
            target = safe_path(self.directory, segment["name"])
            if target is None:
                return
            self.directory.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(descriptor, data)
            finally:
                os.close(descriptor)
            segment["bytes"] += len(data)
            dropped = int(index.get("dropped_segments", 0))
            while len(segments) > MAX_SEGMENTS:
                old = segments.pop(0)
                old_path = safe_path(self.directory, old["name"])
                if old_path is not None:
                    old_path.unlink(missing_ok=True)
                dropped += 1
            DEFAULT_JSON_STORE.write_object(index_path, {"schema_version": 1, "segments": segments,
                "next_order": order + 1, "first_order": segments[0]["first_order"],
                "dropped_segments": dropped, "capture_state": "bounded", "closed": False})
            if identity:
                self.seen.append(fingerprint)
                self.seen = self.seen[-128:]
        except (OSError, ValueError, TypeError, KeyError):
            return

    def consume(self, event: dict, *, provenance: str = "native-json") -> None:
        for record in normalize_event(event, provenance=provenance):
            self.append(record)

    def close(self) -> None:
        path = safe_path(self.directory, INDEX_NAME)
        index = read_index(self.directory)
        if path is not None and index:
            try:
                DEFAULT_JSON_STORE.write_object(path, {**index, "closed": True})
            except OSError:
                pass


def read_index(directory: Path) -> dict:
    path = safe_path(directory, INDEX_NAME)
    if path is None:
        return {}
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.loads(handle.read(16384))
        if isinstance(value, dict) and value.get("schema_version") == 1 and isinstance(value.get("segments"), list):
            if len(value["segments"]) <= MAX_SEGMENTS:
                return value
    except (OSError, ValueError):
        pass
    return {}


def read_events(directory: Path, *, before: int | None = None, limit: int = MAX_PAGE_EVENTS) -> tuple[dict, ...]:
    """Most recent page before order, in original chronological order."""
    index = read_index(directory)
    records: list[dict] = []
    limit = max(1, min(limit, MAX_PAGE_EVENTS))
    for segment in reversed(index.get("segments", [])):
        if not isinstance(segment, dict):
            continue
        path = safe_path(directory, str(segment.get("name", "")))
        if path is None:
            continue
        try:
            with path.open("rb") as handle:
                raw = handle.read(SEGMENT_BYTES + MAX_EVENT_BYTES)
            page = []
            for line in raw.splitlines():
                if len(line) > MAX_EVENT_BYTES:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict) or event.get("source") != "harness" or not isinstance(event.get("order"), int):
                    continue
                if before is None or event["order"] < before:
                    page.append(event)
            records = page + records
            if len(records) >= limit:
                break
        except OSError:
            continue
    return tuple(records[-limit:])


class EventRecorder:
    """Incremental bounded decoder used independently of interactive rendering."""
    def __init__(self, directory: Path, *, structured: bool):
        self.store = EventStore(directory)
        self.structured = structured
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pending = ""

    def feed(self, chunk: bytes) -> None:
        self.pending += self.decoder.decode(chunk)
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self.line(line)
        if len(self.pending) > 262144:
            self.store.append({"kind": "info", "title": "Capture", "body": "Oversized source line omitted", "source": "harness", "capture_state": "bounded"})
            self.pending = ""

    def line(self, line: str) -> None:
        if not line.strip():
            return
        if self.structured:
            try:
                event = json.loads(line)
            except ValueError:
                return
            if isinstance(event, dict):
                self.store.consume(event)
        else:
            self.store.append({"schema_version": 1, "kind": "info", "title": "Agent output",
                               "body": _safe(line), "source": "harness", "provenance": "plain-text", "capture_state": "bounded"})

    def close(self) -> None:
        self.pending += self.decoder.decode(b"", final=True)
        self.line(self.pending)
        self.pending = ""
        self.store.close()
