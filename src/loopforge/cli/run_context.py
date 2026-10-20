"""Bounded, read-only context projections for one run execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopforge.adapters.local_implementation_adapter import observable_stream_text
from loopforge.engine.context_capture import MAX_CAPTURE_BYTES, prompt_sections
from loopforge.engine.path_resolvers import resolve_artifact

MAX_CONTEXT_DISPLAY = 80_000
MAX_MANIFEST_BYTES = 128_000


@dataclass(frozen=True)
class RunContextSection:
    id: str
    title: str
    content: str
    source: str = ""
    authority: str = ""
    expanded: bool = False


@dataclass(frozen=True)
class RunContextSnapshot:
    sections: tuple[RunContextSection, ...] = ()
    raw_prompt: str = ""
    raw_prompt_ref: str = ""
    capture_state: str = ""
    derived: bool = False
    hash_valid: bool | None = None
    redacted: bool = False
    message: str = ""


def _confined(run_dir: Path, reference: str | Path) -> Path:
    """Reject symlinks as well as escapes, even links inside the run root."""
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Context reference must be a relative run path")
    root = run_dir.resolve()
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("Context references cannot traverse links")
    return resolve_artifact(root, str(relative))


def _read(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError("Context artifact exceeds its capture bound")
    return value


def _display(raw: bytes, limit: int = MAX_CONTEXT_DISPLAY) -> tuple[str, bool]:
    text = raw.decode("utf-8", errors="replace")
    clean = observable_stream_text(text, limit=max(len(text) + 1, 1))
    # observable_stream_text intentionally strips surrounding whitespace. Raw
    # display retains it when the content requires no safety transformation.
    if clean == text.strip():
        clean = text
    redacted = "[redacted " in clean and clean != text
    if len(clean) > limit:
        clean = clean[:limit] + "\n[Display bounded; source retained locally.]"
    return clean, redacted


def _section_values(body: bytes, records: list[Any], *, derived: bool) -> tuple[RunContextSection, ...]:
    sections: list[RunContextSection] = []
    budget = MAX_CONTEXT_DISPLAY
    for index, record in enumerate(records[:64]):
        if not isinstance(record, dict):
            continue
        start, end = record.get("start_byte"), record.get("end_byte")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body):
            continue
        if budget <= 0:
            break
        content, _ = _display(body[start:end], min(budget, 16_000))
        budget -= len(content)
        sections.append(RunContextSection(
            id=str(record.get("id") or f"section-{index}")[:128],
            title=observable_stream_text(record.get("title") or "Instructions", limit=120),
            content=content,
            source=observable_stream_text(record.get("source") or "Captured prompt", limit=180),
            authority="derived" if derived else "declared-in-prompt",
            expanded=bool(record.get("expanded")),
        ))
    return tuple(sections)


def load_run_context(run_dir: Path, session_ref: str | Path) -> RunContextSnapshot:
    """Load a selected session only; never regenerate its prompt from a run."""
    try:
        execution_dir = _confined(run_dir, session_ref)
        manifest_path = _confined(run_dir, execution_dir.relative_to(run_dir.resolve()) / "context-manifest.json")
    except (OSError, ValueError):
        return RunContextSnapshot(message="Context reference is outside the selected run.")
    if not manifest_path.exists():
        return _legacy_context(run_dir, execution_dir)
    try:
        manifest = json.loads(_read(manifest_path, MAX_MANIFEST_BYTES))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("Unsupported context manifest")
        raw_ref = manifest["raw_prompt_ref"]
        body_ref = manifest["instructions_ref"]
        if not isinstance(raw_ref, str) or not isinstance(body_ref, str):
            raise ValueError("Invalid context references")
        raw_path = _confined(run_dir, raw_ref)
        body_path = _confined(run_dir, body_ref)
        # A valid hash is insufficient if a manifest rebinds another attempt.
        raw_path.relative_to(execution_dir)
        body_path.relative_to(execution_dir)
        raw = _read(raw_path, MAX_CAPTURE_BYTES)
        body = _read(body_path, MAX_CAPTURE_BYTES)
        valid = (
            hashlib.sha256(raw).hexdigest() == manifest.get("raw_capture_sha256")
            and hashlib.sha256(body).hexdigest() == manifest.get("instructions_sha256")
        )
        complete = manifest.get("capture_state") == "complete"
        if complete:
            valid = valid and hashlib.sha256(raw).hexdigest() == manifest.get("raw_prompt_sha256")
        if not valid:
            return RunContextSnapshot(
                capture_state="invalid", hash_valid=False,
                message="Context hash mismatch; captured instructions are not trusted.",
            )
        records = manifest.get("sections")
        if not isinstance(records, list):
            records = []
        for record in records:
            if isinstance(record, dict) and record.get("content_ref") != body_ref:
                raise ValueError("Context section references a different capture")
        sections = _section_values(body, records, derived=False)
        runner = manifest.get("runner_restrictions")
        if isinstance(runner, list):
            content = "\n".join(value for value in runner[:16] if isinstance(value, str))
            if content:
                sections += (RunContextSection(
                    id="runner", title="Enforced by runner",
                    content=observable_stream_text(content, limit=4000),
                    source="Prompt injection boundary", authority="runner-recorded", expanded=True,
                ),)
        display, redacted = _display(raw)
        _, body_redacted = _display(body)
        return RunContextSnapshot(
            sections=sections,
            raw_prompt=display,
            raw_prompt_ref=raw_ref,
            capture_state="complete" if complete else "bounded",
            hash_valid=True if complete else None,
            redacted=redacted or body_redacted,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return RunContextSnapshot(
            capture_state="invalid", message="Captured context is unavailable or invalid."
        )


def _legacy_context(run_dir: Path, execution_dir: Path) -> RunContextSnapshot:
    for name in ("adapter-prompt.md", "prompt.md"):
        try:
            path = _confined(run_dir, (execution_dir / name).relative_to(run_dir.resolve()))
            raw = _read(path, MAX_CAPTURE_BYTES)
        except (OSError, ValueError):
            continue
        display, redacted = _display(raw)
        sections = _section_values(
            raw, prompt_sections(raw.decode("utf-8", errors="replace")), derived=True
        )
        return RunContextSnapshot(
            sections=sections, raw_prompt=display,
            raw_prompt_ref=path.relative_to(run_dir.resolve()).as_posix(),
            capture_state="derived", derived=True, redacted=redacted,
            message="Derived from a legacy prompt; exact injection was not recorded.",
        )
    return RunContextSnapshot(message="No captured context for this execution.")
