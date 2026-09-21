"""Advisory Claude/Codex hook. No output, decisions, or approval authority."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


MAX_BYTES = 131_072


def record_hook(payload: object, directory: Path, workspace: Path) -> None:
    if not isinstance(payload, dict) or Path(str(payload.get("cwd") or "")).resolve() != workspace.resolve():
        return
    # Do not persist prompts, environment, signatures or arbitrary hook fields.
    event = {key: payload[key] for key in (
        "hook_event_name", "session_id", "transcript_path", "tool_name",
        "tool_use_id", "tool_input", "tool_response", "error", "last_assistant_message",
    ) if key in payload}
    raw = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES // 2:
        event.pop("tool_input", None)
        event.pop("tool_response", None)
        event["error"] = "Tool payload omitted: observation size limit."
        raw = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
    path = directory / "harness-events.jsonl"
    if path.is_symlink() or (path.exists() and path.stat().st_size + len(raw) > MAX_BYTES):
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, raw)
    finally:
        os.close(descriptor)


def main() -> int:
    try:
        directory = Path(os.environ["LOOPFORGE_OBSERVATION_DIR"]).resolve(strict=True)
        workspace = Path(os.environ["LOOPFORGE_OBSERVATION_WORKSPACE"]).resolve(strict=True)
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) <= MAX_BYTES:
            record_hook(json.loads(raw), directory, workspace)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # Observation must never block a tool or steer the agent.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
