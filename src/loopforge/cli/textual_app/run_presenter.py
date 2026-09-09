"""Presentation helpers for the dedicated run Activity surface."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from rich.text import Text

from loopforge.adapters.local_implementation_adapter import observable_stream_text
from loopforge.cli.models import UiSnapshot
from loopforge.cli.presentation import family_presentation, semantic_color
from loopforge.cli.terminal_capabilities import _env_truthy


_TRUSTED_EVENT_KINDS = {
    "artifact written",
    "cancellation requested",
    "check finished",
    "check started",
    "stage started",
}

_TERMINAL_EVENT_SUMMARIES = {
    "blocked": "Operation blocked; inspect retained evidence for details.",
    "cancelled": "Operation cancelled.",
    "completed": "Operation completed.",
    "failed": "Operation failed; inspect retained evidence for details.",
}


def ascii_only() -> bool:
    """Return whether the shared terminal contract requires ASCII glyphs."""

    return _env_truthy("LOOPFORGE_ASCII")


def run_glyph(unicode_value: str, ascii_value: str) -> str:
    return ascii_value if ascii_only() else unicode_value


def terminal_marker(value: object) -> str:
    """Render a shared presentation marker within terminal capabilities."""

    marker = str(value or "")
    if not ascii_only():
        return marker
    return {
        "✓": "+",
        "×": "x",
        "◆": "!",
        "●": "*",
        "◉": "*",
        "○": "o",
        "–": "-",
        "·": ".",
        "›": ">",
    }.get(marker, marker.encode("ascii", errors="replace").decode("ascii"))


def family_color(family: str) -> str:
    """Resolve a family through the shared semantic presentation contract."""

    _, _, role = family_presentation(family)
    return semantic_color(role)


def event_color(kind: str) -> str:
    if kind in {"failed", "blocked", "cancelled"}:
        return semantic_color("danger")
    if kind in {"completed", "check finished", "artifact written", "attempt finished"}:
        return semantic_color("success")
    if kind in {"adapter output", "stage started", "check started"}:
        return semantic_color("running")
    return semantic_color("ready")


def run_activity_text(snapshot: UiSnapshot, *, include_operation_events: bool) -> Text:
    """Build the visible agent output from artifacts and observable events."""

    text = Text()
    shell = snapshot.run.shell
    if shell is None or shell.run is None:
        loading = "Loading agent output..." if ascii_only() else "Loading agent output…"
        text.append(loading, style="#958EA0")
        return text

    stored = snapshot.run.agent.agent_output.strip()
    if stored:
        text.append(stored, style="#CBC3D7")
    events = snapshot.operation.events if include_operation_events else ()
    if not events:
        if not stored:
            waiting = (
                "Agent messages, tool calls, and progress will appear here."
            )
            text.append(waiting, style="#958EA0")
        return text

    for event in events:
        kind = str(getattr(event, "kind", "activity")).replace("_", " ")
        message = activity_event_message(kind, getattr(event, "message", "Working..."))
        lines = message.splitlines() or ["Working..."]
        if len(text):
            text.append("\n")
        text.append(f"{event_marker(kind)} ", style=event_color(kind))
        text.append(lines[0], style="#E7E0ED")
        for line in lines[1:]:
            text.append(f"\n  {line}", style="#CBC3D7")
    return text


def run_attempt_heading(snapshot: UiSnapshot) -> Text:
    """Render the current stage and visible attempt as one compact divider."""

    text = Text()
    shell = snapshot.run.shell
    if shell is None or shell.run is None:
        text.append("--- Loading run ---", style="#958EA0")
        return text
    stage = next(
        (value for value in shell.stages if value.id == shell.run.current_stage),
        None,
    )
    stage_label = str(getattr(stage, "title", "") or shell.run.current_stage or "Run")
    number = snapshot.run.agent.attempt_number
    if number is None and snapshot.run.attempts:
        candidate = snapshot.run.attempts[-1].get("number")
        if isinstance(candidate, int) and not isinstance(candidate, bool):
            number = candidate
    separator = " - " if ascii_only() else " · "
    suffix = f"{separator}Attempt {number:02d}" if number is not None else ""
    text.append(f"--- {stage_label}{suffix} ---", style=semantic_color("attention"))
    return text


def clean_activity_message(value: object) -> str:
    return observable_stream_text(value or "Working...", limit=1600) or "Working..."


def activity_event_message(kind: str, value: object) -> str:
    """Preserve observable adapter output while sanitizing terminal controls."""

    message = clean_activity_message(value)
    if kind in _TERMINAL_EVENT_SUMMARIES:
        return _TERMINAL_EVENT_SUMMARIES[kind]
    if kind in _TRUSTED_EVENT_KINDS:
        return message
    if kind != "adapter output":
        return "Activity update received."
    match = re.match(
        r"^(?P<stage>[\w.-]+)\s+(?P<stream>stdout|stderr):\s*(?P<payload>.*)$",
        message,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        return message
    stage = match.group("stage")
    stream = match.group("stream").lower()
    payload = match.group("payload").strip()
    separator = " - " if ascii_only() else " · "
    if stream == "stderr":
        return f"{stage} stderr{separator}{payload}"
    return payload or f"{stage} stdout"


def activity_time(value: object) -> str:
    if isinstance(value, datetime):
        stamp = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return "--:--:--"
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return "--:--:--"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone().strftime("%H:%M:%S")


def run_progress(stages: tuple[object, ...]) -> str:
    if not stages:
        return "-" if ascii_only() else "—"
    current = next(
        (
            index
            for index, stage in enumerate(stages)
            if str(getattr(stage, "family", "waiting")) != "complete"
        ),
        len(stages) - 1,
    )
    return f"{current + 1}/{len(stages)} steps"


def run_uptime(created_at: str) -> str:
    if not created_at:
        return "-" if ascii_only() else "—"
    try:
        started = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return "-" if ascii_only() else "—"
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}"


def compact_count(value: int | None) -> str:
    if value is None:
        return "-" if ascii_only() else "—"
    if value < 1000:
        return str(value)
    return f"~{value / 1000:.1f}k"


def event_marker(kind: str) -> str:
    if kind in {"failed", "blocked", "cancelled"}:
        return "x" if ascii_only() else "×"
    if kind in {"completed", "check finished", "artifact written"}:
        return "+" if ascii_only() else "✓"
    if kind == "adapter output":
        return ">" if ascii_only() else "›"
    return "." if ascii_only() else "·"


def _family_marker(family: str) -> str:
    if family == "complete":
        return "+" if ascii_only() else "✓"
    if family == "blocked":
        return "x" if ascii_only() else "×"
    return "o" if ascii_only() else "○"
