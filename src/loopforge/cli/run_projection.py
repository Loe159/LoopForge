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
        body = str((value.get("body") or value.get("rendered") or "") if kind == "delegation"
                   else (value.get("rendered") or value.get("body") or ""))[:12000]
        status = str(value.get("status") or "unknown")
        if status not in {"running", "completed", "failed", "unknown"}:
            status = "unknown"
        call_id = str(value.get("call_id") or "")
        native_id = str(value.get("native_id") or "")
        # Claude tool_result exposes the same Call ID, but not the tool name.
        # Join only to an already observed, uniquely identified delegation.
        if kind == "tool" and call_id and ("delegation", call_id) in index_by_native:
            kind = "delegation"
        identity = (kind, call_id or native_id) if kind == "delegation" and (call_id or native_id) else (
            ("tool", call_id) if kind == "tool" and call_id else (
            (kind, native_id) if kind in {"message", "reasoning", "plan", "file_change"} and native_id else None))
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
                declared.append(DeclaredFileChange(
                    path, action, additions, deletions,
                    diff=proof.diff if proof is not None else "",
                    truncated=proof.truncated if proof is not None else False,
                    binary=proof.binary if proof is not None else False,
                ))
        parent_id = value.get("parent_id")
        parent_id = parent_id[:300] if isinstance(parent_id, str) else ""
        source_ids = tuple(identifier for identifier in (call_id, native_id) if identifier)
        mission = value.get("mission")
        mission = mission[:3000] if kind == "delegation" and isinstance(mission, str) else ""
        entry = TranscriptEntry(key, kind, title, body, status, file_changes=tuple(declared),
                                parent_id=parent_id, source_ids=source_ids, mission=mission)
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
                                          file_changes=entry.file_changes or prior.file_changes,
                                          parent_id=entry.parent_id or prior.parent_id,
                                          source_ids=tuple(dict.fromkeys(prior.source_ids + entry.source_ids)),
                                          mission=entry.mission or prior.mission),
                                  old_category or category)
        else:
            if identity:
                index_by_native[identity] = len(rows)
            rows.append((entry, category))
    if session_closed:
        rows = [(replace(item, status="unknown") if item.kind in {"tool", "delegation"} and item.status == "running" else item, cat)
                for item, cat in rows]
    if mode == "All":
        # All retains native chronology; no nested moves or compact read groups.
        return tuple(item for item, _ in rows)

    # Only native IDs from a unique, explicitly typed delegation can own a
    # child. A shared name, matching text, or duplicated ID is not evidence.
    parents_by_id: dict[str, set[int]] = {}
    for position, (entry, _) in enumerate(rows):
        if entry.kind == "delegation":
            for identifier in entry.source_ids:
                parents_by_id.setdefault(identifier, set()).add(position)
    attached: dict[int, int] = {}
    for position, (entry, _) in enumerate(rows):
        matches = parents_by_id.get(entry.parent_id, set()) if entry.parent_id else set()
        if len(matches) == 1:
            (parent,) = matches
            if parent != position:
                attached[position] = parent

    # Malformed/cyclic native relations must not hide events or recurse forever.
    for position in list(attached):
        seen = {position}
        current = position
        while current in attached:
            current = attached[current]
            if current in seen:
                attached.pop(position, None)
                break
            seen.add(current)

    def group_stream(indices: list[int]) -> tuple[TranscriptEntry, ...]:
        output: list[TranscriptEntry] = []
        position = 0
        while position < len(indices):
            index = indices[position]
            entry, category = rows[index]
            if entry.kind == "delegation":
                children = group_stream([n for n, parent in attached.items() if parent == index])
                entry = replace(entry, children=children)
            if entry.kind == "tool" and category in {"read", "search"} and entry.status == "completed":
                end = position + 1
                while end < len(indices):
                    follower, next_category = rows[indices[end]]
                    if follower.kind != "tool" or next_category != category or follower.status != "completed":
                        break
                    end += 1
                if end > position + 1:
                    children = [rows[i][0] for i in indices[position:end]]
                    title = f"Read {len(children)} files" if category == "read" else f"{len(children)} searches"
                    detail = "\n\n".join(f"{item.title} [{item.key}] · {item.status}\n{item.body}" for item in children)
                    output.append(TranscriptEntry("group:" + children[0].key, "group", title, detail, "completed"))
                    position = end
                    continue
            output.append(entry)
            position += 1
        return tuple(output)

    return group_stream([i for i in range(len(rows)) if i not in attached])
