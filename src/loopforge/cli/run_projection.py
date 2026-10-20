"""Stable, authoritative-neutral projections of native observation events."""
from __future__ import annotations
from dataclasses import replace
from typing import Any, Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from loopforge.cli.textual_app.run_presenter import TranscriptEntry, DeclaredFileChange


def project_events(events: tuple[Mapping[str, Any], ...], *,
                   mode: str = "Focused", session_closed: bool = False,
                   verified_changes: Any = None) -> tuple[TranscriptEntry, ...]:
    from loopforge.cli.textual_app.run_presenter import TranscriptEntry, DeclaredFileChange

    # Only the selected session's complete, captured workspace diff can
    # supply +/- figures. Harness-provided numbers are not verification.
    captured: dict[str, Any] = {}
    if (verified_changes is not None and
            getattr(verified_changes, "capture_state", "") == "complete" and
            getattr(verified_changes, "scope", "execution") == "execution" and
            getattr(verified_changes, "source", "") == "runner-workspace-snapshots" and
            not getattr(verified_changes, "stale", False)):
        captured = {file.path: file for file in verified_changes.files}

    rows: list[tuple[TranscriptEntry, str]] = []
    index_by_native: dict[tuple[str, str], int] = {}
    for index, value in enumerate(events):
        kind = str(value.get("kind") or "info")
        if kind not in {"tool", "message", "reasoning", "plan", "delegation", "error", "warning", "file_change", "info"}:
            kind = "info"
        title = str(value.get("title") or kind.title())[:150]
        body = str(value.get("rendered") or value.get("body") or "")[:12000]
        status = str(value.get("status") or "unknown")
        if status not in {"running", "completed", "failed", "unknown"}:
            status = "unknown"
        call_id = str(value.get("call_id") or "")
        native_id = str(value.get("native_id") or "")
        identity = ("tool", call_id) if kind == "tool" and call_id else (
            (kind, native_id) if kind in {"message", "reasoning", "plan", "file_change"} and native_id else None)
        key = ":".join(identity) if identity else "event:" + str(value.get("event_id") or value.get("order", index))
        declared: list[DeclaredFileChange] = []
        if kind == "file_change" and isinstance(value.get("files"), (list, tuple)):
            for file in value["files"][:100]:
                if not isinstance(file, Mapping):
                    continue
                path = file.get("path")
                if not isinstance(path, str) or not path or len(path) > 1024:
                    continue
                action = file.get("action", "unknown")
                if action not in {"modified", "added", "deleted", "renamed"}:
                    action = "unknown"
                proof = captured.get(path)
                # Counts describe the *session-wide* captured diff, not the
                # individual harness event. Never trust counters in value.
                additions = proof.additions if proof is not None else None
                deletions = proof.deletions if proof is not None else None
                declared.append(DeclaredFileChange(path, action, additions, deletions))
        entry = TranscriptEntry(key, kind, title, body, status, file_changes=tuple(declared))
        category = str(value.get("category") or "")
        if identity and identity in index_by_native:
            old_position = index_by_native[identity]
            prior, old_category = rows[old_position]
            if prior.status in {"failed", "completed"} and status == "running":
                continue
            if prior.body and body and prior.body != body and not body.startswith(prior.body):
                body = prior.body + "\n" + body
            rows[old_position] = (replace(entry, title=prior.title if title == "Tool" else title,
                                          body=body or prior.body,
                                          file_changes=entry.file_changes or prior.file_changes),
                                  old_category or category)
        else:
            if identity:
                index_by_native[identity] = len(rows)
            rows.append((entry, category))
    if session_closed:
        rows = [(replace(item, status="unknown") if item.kind == "tool" and item.status == "running" else item, cat)
                for item, cat in rows]
    if mode == "All":
        return tuple(item for item, _ in rows)
    output = []
    position = 0
    while position < len(rows):
        entry, category = rows[position]
        if entry.kind == "tool" and category in {"read", "search"} and entry.status == "completed":
            end = position + 1
            while end < len(rows) and rows[end][0].kind == "tool" and rows[end][1] == category and rows[end][0].status == "completed":
                end += 1
            if end > position + 1:
                children = [item for item, _ in rows[position:end]]
                title = f"Read {len(children)} files" if category == "read" else f"{len(children)} searches"
                detail = "\n\n".join(f"{item.title} [{item.key}] · {item.status}\n{item.body}" for item in children)
                output.append(TranscriptEntry("group:" + children[0].key, "group", title, detail, "completed"))
                position = end
                continue
        output.append(entry)
        position += 1
    return tuple(output)
