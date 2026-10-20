"""Capture the prompt at its injection boundary, without changing execution."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from loopforge.engine.storage import DEFAULT_JSON_STORE

MAX_CAPTURE_BYTES = 2 * 1024 * 1024

_SECTIONS = {
    "Paths": ("environment", "Environment & Git"),
    "Objective": ("mission", "Mission & Role"),
    "Success Checks": ("validation", "Validation & Limits"),
    "Embedded Run Inputs": ("documents", "Injected Documents"),
    "Required Inputs": ("documents", "Injected Documents"),
    "Allowed Tools": ("tools", "Pack, Skills & Tools"),
    "Pack Skills": ("skills", "Pack, Skills & Tools"),
    "Limits": ("limits", "Validation & Limits"),
    "Required Finish": ("output", "Output Contract"),
    "Required Artifact": ("artifact", "Output Contract"),
    "Required Sections": ("required-sections", "Output Contract"),
    "Permission Boundary": ("permissions", "Declared in document"),
    "Pack Agent Instructions": ("instructions", "System Instructions"),
    "Interactive Harness Output Override": ("output-override", "Output Contract"),
}


def prompt_sections(prompt: str) -> list[dict[str, Any]]:
    """Index captured text; section labels never attest enforcement.

    Only level-two headings outside fenced documents are navigation labels.
    The contents remain untrusted prompt text, including embedded instructions.
    """
    markers: list[tuple[int, str]] = [(0, "System Instructions")]
    offset = 0
    fence = ""
    for line in prompt.splitlines(keepends=True):
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            token = match.group(1)
            if not fence:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = ""
        elif not fence and line.startswith("## "):
            title = line[3:].strip()
            if title in _SECTIONS:
                markers.append((offset, title))
        offset += len(line.encode("utf-8"))
    total = len(prompt.encode("utf-8"))
    result: list[dict[str, Any]] = []
    for index, (start, heading) in enumerate(markers):
        end = markers[index + 1][0] if index + 1 < len(markers) else total
        if start >= end:
            continue
        section_id, title = _SECTIONS.get(heading, ("system", heading))
        result.append({
            "id": f"{section_id}-{index}",
            "title": title,
            "source": heading,
            "authority": "declared-in-prompt",
            "start_byte": start,
            "end_byte": min(end, MAX_CAPTURE_BYTES),
            "expanded": section_id in {"mission", "permissions", "output", "artifact"},
        })
    return [section for section in result if section["start_byte"] < MAX_CAPTURE_BYTES]


def _write_private(path: Path, value: bytes) -> None:
    """Atomically store local sensitive input with owner-only permissions."""
    temp_name: str | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".context-", delete=False) as handle:
            temp_name = handle.name
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def archive_stage_context(stage_dir: Path, run_dir: Path) -> str:
    """Preserve the previous execution before the compatibility root is reused."""
    session_id = f"session-{uuid4().hex}"
    files = [path for path in stage_dir.iterdir() if path.name != "sessions"]
    if not files:
        return session_id
    try:
        old = DEFAULT_JSON_STORE.read_object(stage_dir / "context-manifest.json")
        old_id = str(old.get("session_id") or "")
    except (OSError, ValueError):
        old_id = ""
    if not re.fullmatch(r"session-[a-zA-Z0-9_-]+", old_id):
        old_id = f"session-{uuid4().hex}"
    archive = stage_dir / "sessions" / old_id
    if archive.exists():
        archive = stage_dir / "sessions" / f"session-{uuid4().hex}"
    archive.mkdir(parents=True)
    for path in files:
        path.replace(archive / path.name)
    manifest_path = archive / "context-manifest.json"
    if manifest_path.is_file() and not manifest_path.is_symlink():
        old_prefix = stage_dir.relative_to(run_dir).as_posix() + "/"
        new_prefix = archive.relative_to(run_dir).as_posix() + "/"

        def relocate(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: relocate(item) for key, item in value.items()}
            if isinstance(value, list):
                return [relocate(item) for item in value]
            if isinstance(value, str) and value.startswith(old_prefix):
                return new_prefix + value[len(old_prefix):]
            return value

        try:
            DEFAULT_JSON_STORE.write_object(
                manifest_path, relocate(DEFAULT_JSON_STORE.read_object(manifest_path))
            )
        except (OSError, ValueError):
            pass
    return session_id


def capture_prompt_context(
    *,
    run_dir: Path,
    execution_dir: Path,
    run: dict[str, Any],
    stage_id: str,
    session_id: str,
    attempt_id: str | None,
    harness: str,
    prompt: str,
    instructions: str | None = None,
    execution_mode: str,
    timeout_seconds: int,
) -> None:
    """Record exactly the UTF-8 input passed to the harness and referenced text.

    ``instructions`` is supplied only for terminal bootstrap prompts referring
    to a runtime file. It is the same string written to that runtime file.
    The capture grants no additional permissions and does not inspect current
    documents to reconstruct historical context.
    """
    raw = prompt.encode("utf-8")
    body = (instructions if instructions is not None else prompt).encode("utf-8")
    raw_path = execution_dir / "context-raw-prompt.md"
    body_path = execution_dir / "context-instructions.md"
    _write_private(raw_path, raw[:MAX_CAPTURE_BYTES])
    _write_private(body_path, body[:MAX_CAPTURE_BYTES])
    body_ref = body_path.relative_to(run_dir).as_posix()
    sections = prompt_sections(body[:MAX_CAPTURE_BYTES].decode("utf-8", errors="replace"))
    for section in sections:
        section["content_ref"] = body_ref
    # These are runner mechanisms, not claims about harness sandbox flags.
    runner = [
        f"Execution mode: {execution_mode}",
        f"Runner timeout requested: {timeout_seconds} seconds",
    ]
    if stage_id in {"research", "plan", "review"}:
        runner.append(
            "Workspace mutations are detected after execution and block the stage; "
            "this is detection, not filesystem write prevention."
        )
    manifest = {
        "schema_version": 1,
        "run_id": run.get("run_id"),
        "stage_id": stage_id,
        "session_id": session_id,
        "attempt_id": attempt_id,
        "harness": harness,
        "execution_mode": execution_mode,
        "raw_prompt_ref": raw_path.relative_to(run_dir).as_posix(),
        "raw_prompt_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_capture_sha256": hashlib.sha256(raw[:MAX_CAPTURE_BYTES]).hexdigest(),
        "instructions_ref": body_ref,
        "instructions_sha256": hashlib.sha256(body[:MAX_CAPTURE_BYTES]).hexdigest(),
        "capture_state": "complete" if max(len(raw), len(body)) <= MAX_CAPTURE_BYTES else "bounded",
        "raw_prompt_bytes": len(raw),
        "sections": sections,
        "runner_restrictions": runner,
    }
    DEFAULT_JSON_STORE.write_object(execution_dir / "context-manifest.json", manifest)
