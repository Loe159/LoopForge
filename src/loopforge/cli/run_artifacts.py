"""Bounded readers for the run transcript shown by interactive frontends."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

from loopforge.cli.models import RunAgentSnapshot
from loopforge.cli.operations import OperationEvent
from loopforge.engine import StatusResult
from loopforge.engine.path_resolvers import resolve_artifact
from loopforge.adapters.event_store import normalize_event, read_events, read_index, safe_path


_ATTEMPT_NUMBER = re.compile(r"attempt-(?P<number>\d+)$")
_READONLY_STAGES = frozenset({"research", "plan", "review"})
_TERMINAL_ESCAPE = re.compile(
    r"(?:\x1b\][^\x07\x1b]*(?:\x07|\x1b\\))|"
    r"(?:(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~])"
)
_CONTRACT_FIELDS = (
    "status",
    "summary",
    "workspace_changed",
    "deterministic_checks_run",
    "next_action",
)


def list_run_sessions(status: StatusResult) -> tuple[dict[str, Any], ...]:
    """Discover retained execution directories, without mutating run state."""
    if status.run_dir is None or not isinstance(status.run, dict):
        return ()
    root = status.run_dir.resolve()
    sessions: dict[str, dict[str, Any]] = {}
    def add(path: Path, stage: str, attempt: dict | None = None) -> None:
        try:
            relative = str(path.relative_to(root))
        except ValueError:
            return
        confined = safe_path(root, relative)
        if confined is None or not confined.is_dir():
            return
        number = _attempt_number_from_dir(confined) if stage == "implementation" else None
        if relative in sessions and attempt is None:
            return  # Keep metadata from the authoritative run attempt record.
        if not any(safe_path(confined, name) is not None and (confined / name).is_file()
                   for name in ("adapter-prompt.md", "prompt.md", "adapter.stdout", "agent-transcript.log", "agent-events-index.json", "execution.json", "attempt.json")) and attempt is None:
            return
        adapter = str(attempt.get("adapter") or "") if attempt else _stage_adapter(confined)
        sessions[relative] = {"stage_id": stage, "session_id": relative, "session_dir": relative,
                              "attempt_number": number, "adapter": adapter,
                              "label": f"Attempt {number:02d}" if number is not None else "Session",
                              "mtime": _session_mtime(confined)}
    attempts = status.run.get("attempts", [])
    for attempt in attempts if isinstance(attempts, list) else []:
        if isinstance(attempt, dict):
            path = _record_attempt_dir(root, attempt)
            if path is not None:
                add(path, "implementation", attempt)
    attempts_root = safe_path(root, "attempts")
    if attempts_root is not None and attempts_root.is_dir():
        for path in attempts_root.iterdir():
            if _attempt_number_from_dir(path) is not None:
                add(path, "implementation")
    stages_root = safe_path(root, "artifacts/stages")
    if stages_root is not None and stages_root.is_dir():
        for stage_dir in stages_root.iterdir():
            if _stage_from_dir(stage_dir) is None or safe_path(root, str(stage_dir.relative_to(root))) is None:
                continue
            add(stage_dir, stage_dir.name)
            archives = safe_path(stage_dir, "sessions")
            if archives is not None and archives.is_dir():
                for archived in archives.iterdir():
                    add(archived, stage_dir.name)
    ordered = sorted(sessions.values(), key=lambda value: (value["mtime"], value["session_id"]))
    counters: dict[str, int] = {}
    for session in ordered:
        if session["attempt_number"] is None:
            stage = session["stage_id"]
            counters[stage] = counters.get(stage, 0) + 1
            session["label"] = f"Session {counters[stage]:02d}"
    return tuple(ordered)


def load_run_agent_snapshot(
    status: StatusResult,
    events: Iterable[OperationEvent] = (),
    *,
    stage_id: str | None = None,
    session_id: str | None = None,
    before_order: int | None = None,
) -> RunAgentSnapshot:
    """Read one retained session; explicit historical selection never rebinds."""
    if status.run_dir is None or not isinstance(status.run, dict):
        return RunAgentSnapshot()
    run_dir = status.run_dir.resolve()
    events = tuple(events)
    sessions = list_run_sessions(status)
    selected = next((value for value in sessions if value["session_id"] == session_id
                     and (not stage_id or value["stage_id"] == stage_id)), None)
    if session_id and selected is None:
        return RunAgentSnapshot(stage_id=stage_id or "", session_id=session_id)
    if selected is None and stage_id:
        selected = next((value for value in reversed(sessions) if value["stage_id"] == stage_id), None)
        if selected is None:
            return RunAgentSnapshot(stage_id=stage_id)
    if selected is None:
        event_dir = _latest_event_session_dir(run_dir, events)
        selected = next((value for value in sessions if run_dir / value["session_id"] == event_dir), None)
        selected = selected or (sessions[-1] if sessions else None)
    if selected is None:
        return RunAgentSnapshot()
    session_dir = safe_path(run_dir, selected["session_id"])
    if session_dir is None:
        return RunAgentSnapshot()
    number = selected["attempt_number"]
    stage = selected["stage_id"]
    attempts = status.run.get("attempts", [])
    attempt = next((item for item in attempts if isinstance(item, dict) and
                    _positive_int(item.get("number")) == number), None) if number is not None and isinstance(attempts, list) else None
    adapter = selected["adapter"]
    # Foreground events identify an adapter only for their actual session.
    if not adapter and _latest_event_session_dir(run_dir, events) == session_dir:
        adapter = _adapter_from_events(events)
    prompt_path = _artifact_path(run_dir, attempt.get("prompt_path") if attempt else None,
                                 session_dir / ("adapter-prompt.md" if number is not None else "prompt.md"))
    stdout_path = _artifact_path(run_dir, attempt.get("stdout_path") if attempt else None, session_dir / "adapter.stdout")
    transcript_path = _artifact_path(run_dir, None, session_dir / "agent-transcript.log")
    has_transcript = transcript_path is not None and transcript_path.is_file()
    raw_path = transcript_path if has_transcript else stdout_path
    raw = _read_transcript_tail(raw_path, 64_000)
    raw_output = _observable_text(raw, limit=64_000)
    index = read_index(session_dir)
    structured = read_events(session_dir, before=before_order)
    if not index and not has_transcript:
        projected: list[dict[str, Any]] = []
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                for record in normalize_event(event):
                    projected.append({**record, "event_id": f"legacy-{len(projected)}", "order": len(projected)})
        structured = tuple(projected[-500:])
    result_path = _artifact_path(run_dir, attempt.get("result_path") if attempt else None, session_dir / "result.json")
    from loopforge.cli.run_changes import safe_artifact
    result_ref = str(result_path.relative_to(run_dir)) if result_path is not None else ""
    if not result_ref or safe_artifact(run_dir, result_ref) is None or not result_path.is_file():
        result_ref = ""
    return RunAgentSnapshot(
        attempt_number=number,
        adapter=adapter,
        system_prompt=_clean_text(_read_bounded(prompt_path, 131_072)),
        agent_output=_agent_output(raw),
        implementation_contract=_implementation_contract(
            result_path,
            attempt, adapter=adapter, attempt_number=number),
        has_live_transcript=has_transcript,
        stage_id=stage, session_id=selected["session_id"], session_dir=selected["session_id"],
        result_ref=result_ref,
        structured_events=structured, raw_output=raw_output,
        raw_source=str(raw_path.relative_to(run_dir)) if raw_path else "",
        capture_state="bounded" if raw or index else "",
        event_count=int(index.get("next_order", len(structured))),
        first_event_order=int(structured[0].get("order", 0)) if structured else 0,
        has_earlier_events=bool(structured and structured[0].get("order", 0) > index.get("first_order", 0)),
        session_closed=bool(index.get("closed", False)),
    )


def _latest_attempt(run: dict[str, Any]) -> dict[str, Any] | None:
    attempts = run.get("attempts")
    if not isinstance(attempts, list):
        return None
    records = [value for value in attempts if isinstance(value, dict)]
    if not records:
        return None
    return max(records, key=lambda value: _positive_int(value.get("number")) or 0)


def _latest_event_session_dir(
    run_dir: Path,
    events: Iterable[OperationEvent],
) -> Path | None:
    for event in reversed(tuple(events)):
        kind = str(getattr(event, "kind", "")).replace("_", " ")
        if kind not in {
            "attempt started",
            "attempt finished",
            "stage started",
        }:
            continue
        raw = str(getattr(event, "artifact", "") or "").strip()
        if not raw:
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            try:
                candidate = resolve_artifact(run_dir, raw)
            except (OSError, ValueError):
                continue
        try:
            candidate = candidate.resolve()
            candidate.relative_to(run_dir)
        except (OSError, ValueError):
            continue
        if candidate.is_file() or candidate.name == "attempt.json":
            candidate = candidate.parent
        if (
            _attempt_number_from_dir(candidate) is not None
            or _stage_from_dir(candidate) is not None
        ):
            return candidate
    return None


def _latest_stage_dir(run_dir: Path) -> Path | None:
    stages_dir = run_dir / "artifacts" / "stages"
    if not stages_dir.is_dir():
        return None
    candidates: list[Path] = []
    for path in stages_dir.iterdir():
        if not path.is_dir():
            continue
        try:
            candidate = path.resolve()
            candidate.relative_to(run_dir)
        except (OSError, ValueError):
            continue
        if _stage_from_dir(candidate) is not None:
            candidates.append(candidate)
    return max(candidates, key=_session_mtime, default=None)


def _record_attempt_dir(run_dir: Path, attempt: dict[str, Any] | None) -> Path | None:
    if attempt is None:
        return None
    raw = str(attempt.get("attempt_dir") or "").strip()
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            try:
                candidate = resolve_artifact(run_dir, raw)
            except (OSError, ValueError):
                candidate = Path()
        try:
            candidate = candidate.resolve()
            candidate.relative_to(run_dir)
            if _attempt_number_from_dir(candidate) is not None:
                return candidate
        except (OSError, ValueError):
            pass
    number = _positive_int(attempt.get("number"))
    if number is None:
        return None
    try:
        return resolve_artifact(run_dir, f"attempts/attempt-{number:03d}")
    except (OSError, ValueError):
        return None


def _newer_session_dir(first: Path | None, second: Path | None) -> Path | None:
    candidates = [value for value in (first, second) if value is not None]
    if not candidates:
        return None
    return max(candidates, key=_session_mtime)


def _session_mtime(path: Path) -> int:
    timestamps: list[int] = []
    for candidate in (
        path,
        path / "prompt.md",
        path / "adapter-prompt.md",
        path / "adapter.stdout",
        path / "execution.json",
        path / "result.json",
    ):
        try:
            timestamps.append(candidate.stat().st_mtime_ns)
        except OSError:
            continue
    return max(timestamps, default=0)


def _stage_from_dir(path: Path) -> str | None:
    if path.name not in _READONLY_STAGES:
        return None
    if path.parent.name != "stages" or path.parent.parent.name != "artifacts":
        return None
    return path.name


def _stage_snapshot(
    run_dir: Path,
    stage_dir: Path,
    events: Iterable[OperationEvent],
) -> RunAgentSnapshot:
    adapter = _stage_adapter(stage_dir) or _adapter_from_events(events)
    transcript_path = _artifact_path(run_dir, None, stage_dir / "agent-transcript.log")
    has_transcript = transcript_path is not None and transcript_path.is_file()
    return RunAgentSnapshot(
        attempt_number=None,
        adapter=adapter,
        system_prompt=_clean_text(
            _read_text(_artifact_path(run_dir, None, stage_dir / "prompt.md"))
        ),
        agent_output=_agent_output(_read_transcript_tail(transcript_path) if has_transcript else
            _read_bounded(_artifact_path(run_dir, None, stage_dir / "adapter.stdout"), 20_000)),
        implementation_contract="",
        has_live_transcript=has_transcript,
    )


def _stage_adapter(stage_dir: Path) -> str:
    raw = _read_bounded(stage_dir / "execution.json", 4_000)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    return str(payload.get("adapter") or "") if isinstance(payload, dict) else ""


def _attempt_number_from_dir(path: Path) -> int | None:
    match = _ATTEMPT_NUMBER.fullmatch(path.name)
    return int(match.group("number")) if match else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _artifact_path(run_dir: Path, recorded: Any, fallback: Path) -> Path | None:
    raw = str(recorded or "").strip()
    path = Path(raw) if raw else fallback
    if path.is_absolute():
        try:
            path = path.relative_to(run_dir)
        except ValueError:
            return None
    return safe_path(run_dir, str(path))


def _read_bounded(path: Path | None, limit: int) -> str:
    if path is None:
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(limit + 1)
    except OSError:
        return ""


def _read_transcript_tail(path: Path | None, limit: int = 15_000) -> str:
    if path is None:
        return ""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - limit))
            raw = handle.read(limit)
        if size > limit:
            raw = raw.partition(b"\n")[2]
            return "Earlier output omitted; showing recent activity.\n" + raw.decode("utf-8", errors="replace")
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def _read_text(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _clean_text(value: str, limit: int | None = None) -> str:
    raw = _TERMINAL_ESCAPE.sub(
        "", value.replace("\r\n", "\n").replace("\r", "\n")
    )
    clean = "".join(
        char
        for char in raw
        if char in "\n\t" or not unicodedata.category(char).startswith("C")
    ).strip()
    if limit is None or len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "\n… output truncated"


def _agent_output(value: str) -> str:
    lines: list[str] = []
    stream_state: dict[str, Any] = {}
    source = _clean_text(value)
    if len(source) > 18_000:
        source = source[-18_000:].partition("\n")[2]
        source = "Earlier output omitted; showing recent activity.\n" + source
    for raw_line in source.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        try:
            payload = json.loads(line.strip())
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if payload.get("purpose") == "implementation_session_result" or "result_version" in payload:
                continue
            lines.extend(_safe_json_event(payload, stream_state))
            continue
        safe_line = _observable_text(line, limit=4000)
        if safe_line:
            indent = len(line) - len(line.lstrip())
            lines.append(" " * min(indent, 16) + safe_line)
    rendered = _clean_text("\n".join(lines))
    if len(rendered) > 16_000:
        rendered = ("Earlier output omitted; showing recent activity.\n"
                    + rendered[-15_900:].partition("\n")[2])
    return rendered


def _observable_text(value: object, *, limit: int) -> str:
    """Reuse the adapter boundary for unstructured observable output."""

    try:
        from loopforge.adapters.local_implementation_adapter import (
            observable_stream_text,
        )

        return observable_stream_text(value, limit=limit)
    except (ImportError, TypeError, ValueError):
        return ""


def _safe_json_event(event: dict[str, Any], state: dict[str, Any]) -> list[str]:
    """Reuse the adapter's canonical observable Codex event projection."""

    try:
        from loopforge.adapters.local_implementation_adapter import adapter_event_lines

        return adapter_event_lines(event, state)
    except (ImportError, TypeError, ValueError):
        return []


def _implementation_contract(
    path: Path | None,
    attempt: dict[str, Any] | None,
    *,
    adapter: str,
    attempt_number: int | None,
) -> str:
    if attempt is None:
        return ""
    result_origin = str(attempt.get("result_origin") or "").strip()
    if result_origin == "loopforge" or (
        not result_origin and attempt.get("execution_mode") == "terminal"
    ):
        return ""
    payload: dict[str, Any] = {}
    raw = _read_bounded(path, 16_000)
    if not raw:
        return ""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if (
        not isinstance(decoded, dict)
        or not decoded
        or decoded.get("purpose") != "implementation_session_result"
    ):
        return ""
    payload = decoded
    visible: dict[str, Any] = {}
    if attempt_number is not None:
        visible["attempt"] = f"attempt-{attempt_number:03d}"
    if adapter:
        visible["adapter"] = adapter
    for key in _CONTRACT_FIELDS:
        value = payload.get(key)
        if value is None and attempt is not None:
            value = attempt.get(key)
        if isinstance(value, str) and value.strip():
            visible[key] = value
        elif isinstance(value, (bool, int, float)):
            visible[key] = value
    return json.dumps(visible, indent=2, ensure_ascii=False) if visible else ""


def _adapter_from_events(events: Iterable[OperationEvent]) -> str:
    for event in reversed(tuple(events)):
        kind = str(getattr(event, "kind", "")).replace("_", " ")
        if kind not in {"attempt started", "stage started"}:
            continue
        message = str(getattr(event, "message", "") or "")
        match = re.search(
            r"Starting\s+(?:(?P<implementation>[A-Za-z0-9_.-]+)\s+implementation|"
            r"read-only\s+[A-Za-z0-9_.-]+\s+stage\s+with\s+"
            r"(?P<readonly>[A-Za-z0-9_.-]+))",
            message,
        )
        if match:
            return match.group("implementation") or match.group("readonly") or ""
    return ""
