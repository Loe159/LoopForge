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


def load_run_agent_snapshot(
    status: StatusResult,
    events: Iterable[OperationEvent] = (),
) -> RunAgentSnapshot:
    """Read the latest observable agent session inside ``status.run_dir``."""

    if status.run_dir is None or not isinstance(status.run, dict):
        return RunAgentSnapshot()
    run_dir = status.run_dir.resolve()
    attempt = _latest_attempt(status.run)
    event_dir = _latest_event_session_dir(run_dir, events)
    record_attempt_dir = _record_attempt_dir(run_dir, attempt)
    record_stage_dir = _latest_stage_dir(run_dir)
    record_dir = _newer_session_dir(record_attempt_dir, record_stage_dir)
    session_dir = event_dir or record_dir
    if session_dir is None:
        return RunAgentSnapshot()

    if _stage_from_dir(session_dir) is not None:
        return _stage_snapshot(run_dir, session_dir, events)

    number = _attempt_number_from_dir(session_dir)
    record_number = _positive_int(attempt.get("number")) if attempt else None
    use_record = record_attempt_dir == session_dir
    adapter = str(attempt.get("adapter") or "") if attempt and use_record else ""
    if not adapter:
        adapter = _adapter_from_events(events)

    prompt_path = _artifact_path(
        run_dir,
        attempt.get("prompt_path") if attempt and use_record else None,
        session_dir / "adapter-prompt.md",
    )
    stdout_path = _artifact_path(
        run_dir,
        attempt.get("stdout_path") if attempt and use_record else None,
        session_dir / "adapter.stdout",
    )
    result_path = _artifact_path(
        run_dir,
        attempt.get("result_path") if attempt and use_record else None,
        session_dir / "result.json",
    )

    system_prompt = _clean_text(_read_text(prompt_path))
    transcript_path = _artifact_path(run_dir, None, session_dir / "agent-transcript.log")
    has_transcript = transcript_path is not None and transcript_path.is_file()
    agent_output = _agent_output(
        _read_transcript_tail(transcript_path) if has_transcript else _read_bounded(stdout_path, 20_000)
    )
    contract = _implementation_contract(
        result_path,
        attempt if use_record else None,
        adapter=adapter,
        attempt_number=number or record_number,
    )
    return RunAgentSnapshot(
        attempt_number=number or record_number,
        adapter=adapter,
        system_prompt=system_prompt,
        agent_output=agent_output,
        implementation_contract=contract,
        has_live_transcript=has_transcript,
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


def _artifact_path(
    run_dir: Path,
    recorded: Any,
    fallback: Path,
) -> Path | None:
    raw = str(recorded or "").strip()
    if raw:
        try:
            return resolve_artifact(run_dir, raw)
        except (OSError, ValueError):
            return None
    try:
        fallback = fallback.resolve()
        fallback.relative_to(run_dir)
    except (OSError, ValueError):
        return None
    return fallback


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
    for raw_line in _clean_text(value, 18_000).splitlines():
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
    return _clean_text("\n".join(lines), 16_000)


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
