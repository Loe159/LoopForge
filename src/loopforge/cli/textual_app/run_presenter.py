"""Presentation helpers for the dedicated run Activity surface."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, replace
from hashlib import sha256
from datetime import datetime, timezone
from rich.console import Group
from rich.markdown import Markdown, Heading, CodeBlock, BlockQuote, ListItem
from rich.segment import Segment
from rich.style import Style
from rich.theme import Theme
from rich.syntax import Syntax, PygmentsSyntaxTheme
from pygments.style import Style as PygmentsStyle
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from pygments.token import Comment, Keyword, Name, Number, Operator, Punctuation, String
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
        text.append(transcript_text(stored))
    events = snapshot.operation.events if include_operation_events else ()
    if not events:
        if not stored:
            waiting = (
                "Agent messages, tool calls, and progress will appear here."
            )
            text.append(waiting, style="#958EA0")
        return text

    # The engine reports stage completion and the foreground controller reports
    # operation completion. Present one receipt per operation, without dropping
    # either factual event from the engine/history.
    terminal_receipts: set[tuple[str, str]] = set()
    for event in events:
        kind = str(getattr(event, "kind", "activity")).replace("_", " ")
        if kind in _TERMINAL_EVENT_SUMMARIES:
            receipt = (str(getattr(event, "operation_id", "")), kind)
            if receipt in terminal_receipts:
                continue
            terminal_receipts.add(receipt)
        if kind == "adapter output" and (snapshot.run.agent.has_live_transcript or
                (stored and getattr(snapshot.operation, "finished", False))):
            continue  # The run-owned artifact already contains these events.
        message = activity_event_message(kind, getattr(event, "message", "Working..."))
        lines = message.splitlines() or ["Working..."]
        if len(text):
            text.append("\n\n")
        if kind == "adapter output":
            text.append(transcript_text(message))
            continue
        text.append(f"{event_marker(kind)} ", style=event_color(kind))
        text.append(lines[0], style="#E7E0ED")
        for line in lines[1:]:
            text.append(f"\n  {line}", style="#CBC3D7")
    return text


@dataclass(frozen=True)
class DeclaredFileChange:
    """Harness-declared file path; line counts are optional workspace evidence."""

    path: str
    action: str = "unknown"
    additions: int | None = None
    deletions: int | None = None
    diff: str = ""
    truncated: bool = False
    binary: bool = False


@dataclass(frozen=True)
class TranscriptEntry:
    """One visible item; tool identity survives native start/result updates."""

    key: str
    kind: str
    title: str
    body: str
    status: str = ""
    summary: str = ""
    file_changes: tuple[DeclaredFileChange, ...] = ()


@dataclass(frozen=True)
class ToolDisplay:
    """Display-only extraction from known harness journal labels, never a new event."""
    summary: str = ""
    output: str = ""
    output_label: str = ""


def tool_display(entry: TranscriptEntry) -> ToolDisplay:
    """Remove journal envelopes from Live while retaining the original in entry.body.

    Only exact producer labels delimit output. Unknown or partial content stays
    visible rather than being silently discarded.
    """
    body = entry.body
    command = entry.summary
    if not command:
        match = re.search(r"(?m)^\s*\$ (.+)$", body)
        if match:
            command = match.group(1)
    if not command:
        for match in re.finditer(r"(?m)^\s*(?:Input|Arguments):\s*", body):
            try:
                payload, _ = json.JSONDecoder().raw_decode(body[match.end():])
            except ValueError:
                continue
            if isinstance(payload, dict):
                command = str(next((payload[key] for key in (
                    "command", "filePath", "file_path", "path", "pattern", "query"
                ) if isinstance(payload.get(key), str)), ""))
                if command:
                    break

    # Journal output from Codex is an indented 'Output' block. Other
    # supported adapters use explicitly named Result/Output/Error fields.
    matches = list(re.finditer(
        r"(?m)^ {0,2}(Output|Result|Error)(?::[ \t]*|[ \t]*\n)", body
    ))
    if matches:
        marker = matches[-1]
        label = marker.group(1)
        output = body[marker.end():].rstrip()
        if not output and label != "Error":
            output = ""
        else:
            # Codex uses four spaces for retained output; remove that one
            # producer indentation, preserving nested JSON indentation.
            lines = output.splitlines()
            if lines and all(not line.strip() or line.startswith("    ") for line in lines):
                output = "\n".join(line[4:] if line.startswith("    ") else line for line in lines)
        if output:
            return ToolDisplay(command, output, {"Output": "stdout", "Result": "result", "Error": "stderr"}[label])

    # Preserve unknown tool arguments/details. Hide only known redundant
    # wrapper lines and do not repeat a command that already sits in the title.
    content = []
    for line in body.splitlines():
        stripped = line.strip()
        if re.match(r"^(?:MCP )?Tool (?:call|result)(?:\s*\(|\s*·|$)", stripped):
            continue
        if stripped.startswith("Call ID:"):
            continue
        if command and stripped == "$ " + command:
            continue
        if re.fullmatch(r"Exit code: -?\d+", stripped):
            continue
        content.append(line)
    return ToolDisplay(command, "\n".join(content).strip(), "")


class LoopForgeSyntaxStyle(PygmentsStyle):
    """Tool output highlighting aligned with DESIGN.md semantic accents."""
    background_color = "#1D1A23"
    default_style = "#E7E0ED"
    styles = {
        Comment: "#958EA0",
        Keyword: "#D0BCFF",
        Name: "#E7E0ED",
        Name.Tag: "#D0BCFF",
        Name.Attribute: "#D0BCFF",
        String: "#A8E6B0",
        Number: "#FFB869",
        Operator: "#CBC3D7",
        Punctuation: "#958EA0",
    }


_TOOL_SYNTAX_THEME = PygmentsSyntaxTheme(LoopForgeSyntaxStyle)

_DIFF_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def file_diff_renderable(file: DeclaredFileChange) -> Text:
    """Render a retained, session-scoped unified diff as one numbered column.

    The retained Git/difflib hunks already include three context lines. Never
    make up missing context, merge inferred changes, or show headers as code.
    """
    if file.binary:
        return Text("Binary change; no text diff available.", style="#958EA0")
    if not file.diff:
        return Text("Verified diff unavailable for this file.", style="#958EA0")
    try:
        lexer = get_lexer_for_filename(file.path, stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = "text"
    output = Text(no_wrap=True, overflow="crop")
    old_line = new_line = 0
    rows = 0
    in_hunk = False
    for line in file.diff.splitlines():
        match = _DIFF_HUNK.match(line)
        if match:
            if in_hunk and rows:
                output.append("    " + run_glyph("⋯", "...") + "\n", style="#958EA0")
            old_line, new_line = int(match[1]), int(match[2])
            in_hunk = True
            continue
        if not in_hunk or line.startswith("\\ No newline at end of file"):
            continue
        prefix = line[:1]
        if prefix not in {" ", "+", "-"}:
            # A truncated capture can end with a malformed partial line.
            continue
        if rows >= 400:
            output.append("Diff preview limited to 400 lines.\n", style="#958EA0")
            break
        number = old_line if prefix == "-" else new_line
        if prefix != "+":
            old_line += 1
        if prefix != "-":
            new_line += 1
        bg = "#392428" if prefix == "-" else "#20382B" if prefix == "+" else "#1D1A23"
        marker = prefix if prefix in {"+", "-"} else " "
        start = len(output)
        output.append(f"{number:>4} {marker} ", style="#958EA0" if prefix == " " else "#FFB4AB" if prefix == "-" else "#A8E6B0")
        code = line[1:]
        output.append_text(Syntax(code, lexer, theme=_TOOL_SYNTAX_THEME, background_color=bg).highlight(code))
        # Syntax colors take priority; the line's background remains visible.
        output.stylize(f"on {bg}", start, len(output))
        output.append("\n")
        rows += 1
    if not rows:
        return Text("No parseable diff hunks in retained capture.", style="#958EA0")
    if file.truncated:
        output.append("Diff preview truncated by capture limit.\n", style="#FFB869")
    return output


def tool_output_renderable(value: str) -> Text | Syntax | Group:
    """Syntax-highlight confirmed JSON, not arbitrary terminal output."""
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        return agent_body_renderable(value, tool_output=True)
    if isinstance(decoded, (dict, list)):
        return Syntax(value, "json", theme=_TOOL_SYNTAX_THEME, background_color="#1D1A23",
                      word_wrap=True, line_numbers=False, padding=(0, 1))
    return agent_body_renderable(value, tool_output=True)


class AgentHeading(Heading):
    """Compact, left-aligned headings in the existing terminal type scale."""

    def __rich_console__(self, console, options):
        heading = self.text.copy()
        heading.justify = "left"
        heading.stylize("bold #E7E0ED")
        yield heading


class AgentCodeBlock(CodeBlock):
    """Language-aware code with a recessed background, never Rich markup."""

    def __rich_console__(self, console, options):
        language = "bash" if self.lexer_name in {"sh", "shell"} else self.lexer_name
        code = str(self.text).rstrip("\n")
        syntax = Syntax(
            code, language, theme=_TOOL_SYNTAX_THEME,
            background_color="#1D1A23", line_numbers=False,
            word_wrap=True, padding=(0, 1),
        )
        if syntax.lexer is None:
            syntax = Syntax(
                code, "text", theme=_TOOL_SYNTAX_THEME,
                background_color="#1D1A23", word_wrap=True, padding=(0, 1),
            )
        if language != "text":
            yield Text(language, style="#958EA0")
        yield syntax


class AgentBlockQuote(BlockQuote):
    """A quiet quote rail, distinct from the Agent Message's outer rail."""

    def __rich_console__(self, console, options):
        lines = console.render_lines(
            self.elements, options.update(width=max(1, options.max_width - 2)),
            style=console.get_style("#CBC3D7"),
        )
        for line in lines:
            yield Segment("| " if ascii_only() else "│ ", Style(color="#494454"))
            yield from line
            yield Segment.line()


class AgentListItem(ListItem):
    """Quiet bullets; ASCII terminals never receive generated Unicode markers."""

    def render_bullet(self, console, options):
        lines = console.render_lines(
            self.elements, options.update(width=max(1, options.max_width - 3)),
            style=console.get_style("#E7E0ED"),
        )
        marker = " * " if ascii_only() else " • "
        for index, line in enumerate(lines):
            yield Segment(marker if index == 0 else "   ", Style(color="#958EA0"))
            yield from line
            yield Segment.line()


_AGENT_MARKDOWN_THEME = Theme({
    # Rich's default markdown.code is cyan on black; on our dark palette this
    # hides file names. Keep both foreground and background explicit.
    "markdown.code": "bold #D0BCFF on #30283B",
    # Rich's default quotation color is too dim on the Live surface.
    "markdown.block_quote": "#CBC3D7",
})


class AgentMarkdown(Markdown):
    """Rich Markdown for untrusted agent prose, without clickable links."""

    elements = {
        **Markdown.elements,
        "heading_open": AgentHeading,
        "fence": AgentCodeBlock,
        "code_block": AgentCodeBlock,
        "blockquote_open": AgentBlockQuote,
        "list_item_open": AgentListItem,
    }

    def __rich_console__(self, console, options):
        # Scope Markdown accents to this message; never mutate the application
        # theme, other widgets, or the Tool Call rendering.
        with console.use_theme(_AGENT_MARKDOWN_THEME):
            yield from super().__rich_console__(console, options)


def agent_message_renderable(value: str) -> Text | AgentMarkdown:
    """Format agent prose safely, avoiding layout churn for plain streaming text.

    Rich's Markdown layout is only needed for formatted content; plain messages
    stay as Text and retain their exact line breaks. Raw retains the original
    value regardless. Links in formatted messages are never clickable.
    """
    markdown = AgentMarkdown(value, style="#E7E0ED", hyperlinks=False)
    if all(
        token.type in {"paragraph_open", "inline", "paragraph_close"} and
        (token.type != "inline" or all(
            child.type in {"text", "softbreak", "hardbreak"}
            for child in (token.children or ())
        ))
        for token in markdown.parsed
    ):
        return Text(value, style="#E7E0ED")
    return markdown


def transcript_entries(value: str) -> tuple[TranscriptEntry, ...]:
    """Reduce LoopForge's own readable blocks, not terminal repaint bytes.

    New journals retain native Call IDs. Legacy journals merge only an
    unambiguous pending call with matching command/name, never two completed
    calls or concurrent calls with the same name.
    """

    blocks: list[list[str]] = []
    for line in value.splitlines():
        if not line.strip() and not line.startswith("  "):
            continue
        if not line.startswith(" ") or not blocks:
            blocks.append([line])
        else:
            blocks[-1].append(line)
    entries: list[TranscriptEntry] = []
    indices: dict[str, int] = {}
    occurrences: dict[str, int] = {}
    for block in blocks:
        heading, *lines = block
        tool = any(heading == label or heading.startswith((label + " (", label + " · ", label + " - "))
                   for label in ("Tool call", "MCP tool call", "Tool result"))
        kind = ("tool" if tool else "message" if heading == "Agent message" else
                "reasoning" if heading == "Reasoning" else "info")
        call_id = ""
        if tool and lines and lines[0].startswith("  Call ID: "):
            try:
                candidate = json.loads(lines[0][len("  Call ID: "):])
                if isinstance(candidate, str):
                    call_id = candidate
                    lines.pop(0)
            except ValueError:
                pass
        body = "\n".join(line[2:] if line.startswith("  ") else line for line in lines)
        status, title, summary = "", heading, ""
        if tool:
            parts = re.split(r" · | - ", heading, maxsplit=1)
            label = parts[0]
            title = parts[1] if len(parts) == 2 else "Tool"
            metadata_match = re.search(r"\(([^)]*)\)", label)
            metadata = metadata_match.group(1).casefold() if metadata_match else ""
            failed = re.search(r"\b(?:failed|error)\b|exit (?!0(?:\D|$))-?\d+", metadata)
            status = ("failed" if failed else "completed" if
                      "completed" in metadata or label.startswith("Tool result") else
                      "running" if any(s in metadata for s in ("in_progress", "running", "pending"))
                      or not metadata else "unknown")
            command = next((line[2:] for line in body.splitlines() if line.startswith("$ ")), "")
            if command and title == "Tool":
                title = "Shell"
            summary = command
            if not summary:
                raw_input = body.split("\nOutput:", 1)[0].removeprefix("Input: ")
                try:
                    payload = json.loads(raw_input)
                    if isinstance(payload, dict):
                        summary = str(next((payload[k] for k in
                            ("command", "filePath", "file_path", "path", "pattern", "query") if k in payload), ""))
                except ValueError:
                    pass
            exit_code = re.search(r"\bexit (-?\d+)\b", metadata)
            if exit_code:
                body += f"\nExit code: {exit_code.group(1)}"
        fingerprint = sha256((kind + heading + body).encode()).hexdigest()[:20]
        occurrences[fingerprint] = occurrences.get(fingerprint, 0) + 1
        key = "call:" + call_id if call_id else f"{fingerprint}:{occurrences[fingerprint]}"
        entry = TranscriptEntry(key, kind, title, body, status, summary)
        index = indices.get(key) if call_id else None
        if tool and not call_id and status in {"completed", "failed"}:
            candidates = [i for i, previous in enumerate(entries)
                          if previous.kind == "tool" and previous.status == "running"
                          and previous.title == title and (not summary or previous.summary == summary)]
            if len(candidates) == 1:
                index = candidates[0]
        if index is not None:
            previous = entries[index]
            # Some hooks return only the result, others a full replacement.
            if heading.startswith("Tool result"):
                result = "\nOutput:\n" + body if body else ""
                body = previous.body if previous.body.endswith(result) else previous.body + result
            if previous.status in {"completed", "failed"} and status == "running":
                continue  # Delayed start events must not restart a finished tool.
            entries[index] = replace(entry, key=previous.key, body=body,
                title=previous.title if title == "Tool" else title,
                summary=summary or previous.summary)
        else:
            indices[key] = len(entries)
            entries.append(entry)
    return tuple(entries)


def transcript_text(value: str) -> Text:
    """Style the shared readable transcript without interpreting agent markup."""

    text = Text()
    headings = ("Reasoning", "Agent message", "Tool call", "MCP tool call",
                "Tool result", "File change", "Web search", "Plan", "Usage",
                "Agent error", "Adapter error")
    for line in value.splitlines():
        heading = not line.startswith(" ") and any(
            line == label or line.startswith(label + " (") or line.startswith(label + " ·")
            for label in headings
        )
        if len(text):
            text.append("\n\n" if heading else "\n")
        if heading:
            role = "danger" if "error" in line.lower() or "failed" in line.lower() else "ready"
            text.append(line.replace(" · ", " - ") if ascii_only() else line,
                        style=f"bold {semantic_color(role)}")
        else:
            text.append(line, style="#CBC3D7")
    return text


def _tool_output_text(value: str) -> Text:
    """Color explicit journal commands and JSON fields without guessing logs."""

    text = Text(value, style="#E7E0ED")
    ranges: list[tuple[int, int, str]] = []
    for match in re.finditer(r"^\$ (.+)$", value, re.MULTILINE):
        ranges.append((match.start(1), match.end(1), "bash"))
    for match in re.finditer(r"^(?:Input|Arguments|Result):\s*", value, re.MULTILINE):
        start = match.end()
        try:
            payload, length = json.JSONDecoder().raw_decode(value[start:])
        except ValueError:
            continue
        if isinstance(payload, (dict, list)):
            ranges.append((start, start + length, "json"))
    for start, end, language in ranges:
        highlighted = Syntax("", language, theme="ansi_dark", tab_size=0).highlight(value[start:end])
        for span in highlighted.spans:
            text.stylize(span.style, start + span.start, min(start + span.end, end))
    return text


def agent_body_renderable(value: str, *, tool_output: bool = False) -> Text | Syntax | Group:
    """Render agent prose and fenced code while keeping untrusted text literal.

    Agent responses are commonly Markdown, but the transcript is deliberately
    not passed through Rich's Markdown parser: terminal control sequences and
    Rich markup must remain literal. Explicit fenced blocks give us a safe,
    deterministic boundary for syntax highlighting without changing prose.
    """

    lines = value.splitlines()
    parts: list[Text | Syntax] = []
    prose: list[str] = []
    code: list[str] = []
    language = "text"
    delimiter = ""
    indentation = 0

    def flush_prose() -> None:
        if prose:
            value = "\n".join(prose)
            parts.append(_tool_output_text(value) if tool_output else Text(value, style="#E7E0ED"))
            prose.clear()

    def flush_code() -> None:
        if code:
            syntax = Syntax(
                "\n".join(code),
                "bash" if language == "shell" else language,
                theme="ansi_dark",
                background_color="#1D1A23",
                line_numbers=False,
                word_wrap=True,
                padding=(0, 1),
            )
            if syntax.lexer is None:
                syntax = Syntax(syntax.code, "text", theme="ansi_dark",
                                background_color="#1D1A23", word_wrap=True, padding=(0, 1))
            parts.append(syntax)
            code.clear()

    for line in lines:
        if delimiter:
            closing = re.fullmatch(r" *([`~]+)\s*", line)
            if (closing and set(closing.group(1)) == {delimiter[0]}
                    and len(closing.group(1)) >= len(delimiter)):
                flush_code()
                delimiter = ""
            else:
                # Remove only the opening fence's indentation, keeping code layout.
                removed = min(indentation, len(line) - len(line.lstrip(" ")))
                code.append(line[removed:])
            continue
        fence = re.fullmatch(r"( *)(`{3,}|~{3,})[ \t]*([^\n]*)", line)
        if fence and not (fence.group(2)[0] == "`" and "`" in fence.group(3)):
            flush_prose()
            indentation = len(fence.group(1))
            delimiter = fence.group(2)
            info = fence.group(3).split()
            language = info[0].casefold() if info else "text"
        else:
            prose.append(line)
    if delimiter:
        # An interrupted live stream should still show its partial code block.
        flush_code()
    flush_prose()
    if not parts:
        return Text()
    return parts[0] if len(parts) == 1 else Group(*parts)


def run_attempt_heading(snapshot: UiSnapshot) -> Text:
    """Render the current stage and visible attempt as one compact divider."""

    text = Text()
    shell = snapshot.run.shell
    if shell is None or shell.run is None:
        text.append("--- Loading run ---", style="#958EA0")
        return text
    selected_id = snapshot.run.reading.stage_id or snapshot.run.agent.stage_id or shell.run.current_stage
    stage = next((value for value in shell.stages if value.id == selected_id), None)
    stage_label = str(getattr(stage, "title", "") or selected_id or "Run")
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
    return observable_stream_text(value or "Working...", limit=8000) or "Working..."


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
