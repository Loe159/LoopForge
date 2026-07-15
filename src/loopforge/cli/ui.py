"""Terminal rendering helpers for LoopForge."""

from __future__ import annotations

import importlib.util
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Iterable, TextIO

from loopforge.engine import GuidedAction, profile_permission_lines
from loopforge.cli.actions import action_descriptors
from loopforge.cli.presentation import shell_snapshot, workflow_progress


STATUS_STYLES = {
    "verified": "ok",
    "passed": "ok",
    "complete": "ok",
    "completed": "ok",
    "valid": "ok",
    "ready_for_verification": "attention",
    "loop_contract_ready": "attention",
    "loop_contract_draft": "attention",
    "not initialized": "attention",
    "not run": "muted",
    "missing": "blocked",
    "failed": "blocked",
    "verification_failed": "blocked",
    "adapter_blocked": "blocked",
    "invalid": "blocked",
}


class TerminalRenderer:
    """Small Rich-aware renderer with a plain text fallback."""

    def __init__(
        self,
        output: TextIO,
        *,
        mode: str = "auto",
        theme: str = "default",
        no_color: bool = False,
    ) -> None:
        self.output = output
        self.mode = mode
        self.theme = theme
        self.no_color = no_color
        self.rich_available = importlib.util.find_spec("rich") is not None
        self.console = None
        self.use_rich = False
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        no_color = (
            self.no_color
            or os.environ.get("NO_COLOR") is not None
            or os.environ.get("LOOPFORGE_NO_COLOR") is not None
            or os.environ.get("TERM") == "dumb"
        )
        force_color = os.environ.get("FORCE_COLOR") is not None and not no_color
        is_tty = hasattr(self.output, "isatty") and self.output.isatty()
        auto_rich = (
            mode == "auto"
            and self.rich_available
            and (is_tty or force_color)
            and not no_color
        )
        self.use_rich = (mode == "rich" and self.rich_available and not no_color) or auto_rich
        if self.use_rich:
            from rich.console import Console

            self.console = Console(
                file=self.output,
                force_terminal=True,
                color_system="standard" if mode == "rich" else None,
                no_color=no_color,
                highlight=False,
            )
        else:
            self.console = None

    def print(self, message: str = "", *, style: str | None = None) -> None:
        if self.use_rich and self.console is not None:
            self.console.print(message, style=self.style(style))
            return
        print(message, file=self.output)

    def panel(self, title: str, lines: list[str]) -> None:
        if self.use_rich and self.console is not None:
            from rich.panel import Panel

            self.console.print(
                Panel("\n".join(lines), title=title, border_style=self.style("action"))
            )
            return
        print(title, file=self.output)
        for line in lines:
            print(line, file=self.output)

    def section(self, title: str, lines: list[str]) -> None:
        if self.use_rich and self.console is not None:
            from rich.rule import Rule

            self.console.print(Rule(title, style=self.style("muted")))
            for line in lines:
                self.console.print(line)
            return
        print(title, file=self.output)
        for line in lines:
            print(line, file=self.output)

    def table(self, title: str, columns: list[str], rows: list[list[str]]) -> None:
        if self.use_rich and self.console is not None:
            from rich.table import Table

            table = Table(title=title, box=None, pad_edge=False)
            for column in columns:
                table.add_column(column, style=self.style("muted" if column == columns[0] else None))
            for row in rows:
                table.add_row(*row)
            self.console.print(table)
            return
        print(title, file=self.output)
        print(" | ".join(columns), file=self.output)
        for row in rows:
            print(" | ".join(row), file=self.output)

    def loading(self, message: str):
        if self.use_rich and self.console is not None:
            return self.console.status(message, spinner="dots", spinner_style=self.style("action"))
        return nullcontext()

    def status_badge(self, value: object) -> str:
        text = str(value or "unknown")
        if not self.use_rich:
            return text
        style = STATUS_STYLES.get(text, STATUS_STYLES.get(text.lower(), "muted"))
        return f"[{self.style(style)}]{text}[/]"

    def command(self, command: object) -> str:
        text = str(command or "")
        if self.use_rich:
            return f"[{self.style('command')}]{text}[/]"
        return text

    def style(self, role: str | None) -> str | None:
        if role is None:
            return None
        if self.theme == "mono":
            return None
        palette = {
            "brand": "bold cyan",
            "primary": None,
            "secondary": "dim",
            "ready": "cyan",
            "running": "bright_cyan",
            "success": "green",
            "danger": "bold red",
            "selected": "reverse bold",
            "code": "cyan",
            "ok": "green",
            "attention": "yellow",
            "blocked": "red",
            "error": "red",
            "action": "cyan",
            "command": "bold cyan",
            "muted": "dim",
            "details": "dim",
        }
        if self.theme == "light":
            palette["muted"] = "black"
            palette["details"] = "black"
        return palette.get(role)


def compact_path(value: object, *, project_dir: Path | None = None) -> str:
    if value is None:
        return "none"
    path = Path(str(value))
    if project_dir is not None:
        try:
            return path.resolve().relative_to(project_dir.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return str(path)


def compact_text(value: object, *, limit: int = 96) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def not_reported(value: object) -> str:
    if value is None:
        return "not reported"
    if isinstance(value, str) and value in {"", "unknown", "unavailable"}:
        return "not reported"
    return str(value)


def yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"


def summary_table_lines(rows: Iterable[tuple[str, object]], *, key_width: int | None = None) -> list[str]:
    normalized = [(str(key), str(value)) for key, value in rows]
    width = key_width if key_width is not None else max((len(key) for key, _ in normalized), default=0)
    return [f"{key:<{width}}  {value}" for key, value in normalized]


def render_next(renderer: TerminalRenderer, command: object | None) -> list[str]:
    if not command:
        return []
    return ["", "Next", renderer.command(command)]


def render_summary_table(
    renderer: TerminalRenderer,
    title: str,
    rows: Iterable[tuple[str, object]],
    *,
    next_command: object | None = None,
    extra_lines: Iterable[str] = (),
) -> None:
    lines = summary_table_lines(rows)
    lines.extend(str(line) for line in extra_lines)
    lines.extend(render_next(renderer, next_command))
    renderer.panel(title, lines)


def render_success(
    renderer: TerminalRenderer,
    title: str,
    rows: Iterable[tuple[str, object]],
    *,
    next_command: object | None = None,
) -> None:
    render_summary_table(renderer, title, rows, next_command=next_command)


def render_blocked(
    renderer: TerminalRenderer,
    title: str,
    rows: Iterable[tuple[str, object]],
    *,
    blockers: Iterable[str] = (),
    next_command: object | None = None,
) -> None:
    extra: list[str] = []
    blocker_list = [str(blocker) for blocker in blockers]
    if blocker_list:
        extra.append("")
        extra.append("Blockers")
        extra.extend(f"- {blocker}" for blocker in blocker_list)
    render_summary_table(renderer, title, rows, next_command=next_command, extra_lines=extra)


def average_text(series: object) -> str:
    if not isinstance(series, dict):
        return "unknown"
    average = series.get("average")
    if average is None:
        return "unknown"
    if isinstance(average, float):
        return f"{average:.2f}".rstrip("0").rstrip(".")
    return str(average)


def action_lines(action: GuidedAction | None) -> list[str]:
    if action is None:
        return ["next action: none"]
    return [
        f"next action: [{action.id}] {action.label}",
        f"command: {action.command}",
        f"why: {action.why}",
    ]


def blockers_lines(blockers: list[str]) -> list[str]:
    if blockers:
        return ["blockers:", *[f"- {blocker}" for blocker in blockers]]
    return ["blockers:", "- none"]


def format_status_lines(result: Any, guidance: Any, *, details: bool = False) -> list[str]:
    snapshot = shell_snapshot(result, guidance)
    action = snapshot.actions[0] if snapshot.actions else None
    command = action.command_fallback if action is not None else result.next_step
    lines: list[str] = []

    if not result.initialized:
        rows: list[tuple[str, object]] = [
            ("status", "not initialized"),
            ("project", result.project_dir.name),
            ("config", compact_path(result.config_path, project_dir=result.project_dir)),
        ]
        if result.blockers:
            rows.append(("blocker", compact_text(result.blockers[0], limit=80)))
        lines.extend(summary_table_lines(rows))
        if details:
            lines.extend(["", "Details", f"config: {result.config_path}"])
            lines.extend(blockers_lines(result.blockers))
        lines.extend(["", "Next", str(command or "loopforge init")])
        return lines

    config = result.config or {}

    if result.run is None:
        rows = [
            ("status", "ready_for_run"),
            ("project", result.project_dir.name),
            ("profile", config.get("profile") or "unknown"),
            ("run", config.get("current_run_id") or "none"),
        ]
        if result.blockers:
            rows.append(("blocker", compact_text(result.blockers[0], limit=80)))
        lines.extend(summary_table_lines(rows))
        if details:
            lines.extend(_status_detail_lines(result))
            lines.extend(blockers_lines(result.blockers))
        lines.extend(["", "Next", str(command or 'loopforge run --task "..."')])
        return lines

    run = result.run
    checks = 0
    if result.loop_contract is not None:
        checks = len(result.loop_contract.get("success_checks", []))
    if result.verification is not None:
        verification = result.verification
        verify = verification.get("status", "unknown")
    else:
        verify = "not run"
    workflow_step, workflow_actor, _ = workflow_progress(run)
    rows = [
        ("status", run.get("status") or "unknown"),
        ("step", workflow_step),
        ("actor", workflow_actor),
        ("run", run.get("run_id") or "none"),
        ("task", compact_text(run.get("task"), limit=90)),
        ("pack", run.get("pack") or "none"),
        ("checks", f"{checks} success checks"),
        ("verify", verify),
    ]
    if result.blockers:
        rows.append(("blocker", compact_text(result.blockers[0], limit=80)))
    lines.extend(summary_table_lines(rows))
    _append_artifact_attention(lines, result)
    if details:
        lines.extend(_status_detail_lines(result))
        lines.extend(blockers_lines(result.blockers))
    lines.extend(["", "Next", str(command or result.next_step)])
    return lines


def _append_artifact_attention(lines: list[str], result: Any) -> None:
    native = result.native_artifacts or {}
    if native.get("status") not in {None, "complete"}:
        lines.append(
            f"native artifacts: {native.get('status')} ({native.get('present')}/{native.get('total')})"
        )


def _status_detail_lines(result: Any) -> list[str]:
    lines = ["", "details:"]
    if result.config is not None:
        lines.append(f"run root: {result.config.get('run_root')}")
        lines.append(f"default adapter: {result.config.get('default_adapter')}")
        lines.append(
            "default adapter args: "
            + " ".join(str(arg) for arg in result.config.get("default_adapter_args", []))
        )
        lines.extend(profile_permission_lines(result.config.get("profile")))

    if result.run is not None:
        run = result.run
        lines.append(f"base commit: {run.get('base_commit') or 'none'}")
        lines.append(f"run directory: {result.run_dir}")
        lines.append(f"workflow stage: {run.get('current_stage') or 'task_draft'}")
        _, _, workflow_lines = workflow_progress(run)
        if workflow_lines:
            lines.append("workflow:")
            lines.extend(workflow_lines)
        workspace = run.get("workspace", {})
        if isinstance(workspace, dict) and workspace:
            lines.append(f"workspace mode: {workspace.get('mode') or 'unknown'}")
            lines.append(f"workspace: {workspace.get('path') or 'none'}")
        contract = run.get("pack_contract", {})
        if isinstance(contract, dict):
            if contract.get("source"):
                lines.append(f"pack source: {contract['source']}")
            if contract.get("detection"):
                lines.append(f"pack selection: {contract['detection']}")
            skills = contract.get("skills", [])
            if isinstance(skills, list):
                lines.append(f"pack skills: {len(skills)}")
                lines.extend(f"- {skill}" for skill in skills)
            agents = contract.get("agents", [])
            if isinstance(agents, list):
                lines.append(f"pack agents: {len(agents)}")
                lines.extend(
                    f"- {agent.get('id')}: {agent.get('mode')}"
                    for agent in agents
                    if isinstance(agent, dict)
                )

    lines.extend(_native_artifact_lines(result.native_artifacts))
    lines.extend(_loop_contract_lines(result.loop_contract))
    lines.extend(_verification_lines(result.verification))
    lines.extend(_memory_lines(result.memory))
    return lines


def _native_artifact_lines(state: dict[str, object] | None) -> list[str]:
    if state is None:
        return []
    lines = [f"native artifacts: {state['status']} ({state['present']}/{state['total']})"]
    missing_files = state.get("missing_files", [])
    missing_directories = state.get("missing_directories", [])
    if missing_files:
        lines.append(f"native missing files: {', '.join(str(name) for name in missing_files)}")
    if missing_directories:
        lines.append(
            f"native missing directories: {', '.join(str(name) for name in missing_directories)}"
        )
    return lines


def _loop_contract_lines(state: dict[str, object] | None) -> list[str]:
    if state is None:
        return []
    lines = [
        f"loop contract: {state['status']}",
        f"success checks: {len(state.get('success_checks', []))}",
        f"subjective: {'yes' if state.get('subjective') else 'no'}",
    ]
    if state.get("subjective"):
        lines.append(f"rubric: {'present' if state.get('rubric') else 'missing'}")
    errors = state.get("errors", [])
    if errors:
        lines.append("loop contract notes:")
        lines.extend(f"- {error}" for error in errors)
    return lines


def _verification_lines(state: dict[str, object] | None) -> list[str]:
    if state is None:
        return []
    lines = [f"verification: {state.get('status', 'unknown')}"]
    patch = state.get("patch", {})
    if isinstance(patch, dict):
        lines.append(f"patch: {patch.get('path') or 'none'}")
        lines.append(f"patch size bytes: {patch.get('size_bytes', 0)}")
    diff_policy = state.get("diff_policy", {})
    if isinstance(diff_policy, dict):
        lines.append(f"diff policy allowed: {diff_policy.get('allowed')}")
    risk = state.get("risk", {})
    if isinstance(risk, dict):
        lines.append(f"risk: {risk.get('risk') or 'unknown'}")
        if risk.get("policy"):
            lines.append(f"risk policy: {risk['policy']}")
    lines.append(f"pack checks: {state.get('checks_passed', 0)}/{state.get('checks_total', 0)}")
    if state.get("stagnated"):
        lines.append("stagnation: yes")
    return lines


def _memory_lines(state: dict[str, object] | None) -> list[str]:
    if state is None:
        return []
    lines = [
        f"durable memory: {state.get('durable_items', 0)} items",
        f"durable memory path: {state.get('durable_path') or 'none'}",
        f"run memory snapshot: {state.get('run_snapshot') or 'none'}",
        (
            "memory proposals: "
            f"{state.get('pending', 0)} pending, "
            f"{state.get('promoted', 0)} promoted, "
            f"{state.get('rejected', 0)} rejected"
        ),
    ]
    if state.get("proposal_path"):
        lines.append(f"memory proposal path: {state['proposal_path']}")
    return lines


def render_status(renderer: TerminalRenderer, result: Any, guidance: Any, *, details: bool) -> None:
    lines = format_status_lines(result, guidance, details=details)
    renderer.panel("Current loop", lines)


def render_guidance(renderer: TerminalRenderer, guidance: Any, *, include_also: bool = True) -> None:
    actions = action_descriptors(guidance)
    action = actions[0] if actions else None
    lines = ["You are here", guidance.summary]
    reasons = guidance.blocked_reasons or guidance.diagnostics or guidance.evidence
    if reasons:
        lines.extend(["", "Why", compact_text(reasons[0], limit=120)])
    elif action is not None:
        lines.extend(["", "Why", compact_text(action.description, limit=120)])
    if action is not None:
        lines.extend(["", "Do this", renderer.command(action.command_fallback)])
    if include_also and len(actions) > 1:
        lines.extend(["", "Also useful"])
        for extra in actions[1:4]:
            lines.append(f"- {extra.command_fallback}")
    renderer.panel("Guide", lines)


def render_dashboard(renderer: TerminalRenderer, snapshot: dict[str, Any], *, details: bool = False) -> None:
    project = snapshot.get("project", {}) if isinstance(snapshot.get("project"), dict) else {}
    runs = snapshot.get("runs", {}) if isinstance(snapshot.get("runs"), dict) else {}
    current = (
        snapshot.get("current_loop", {})
        if isinstance(snapshot.get("current_loop"), dict)
        else {}
    )
    attempts = snapshot.get("attempts", {}) if isinstance(snapshot.get("attempts"), dict) else {}
    verification = (
        snapshot.get("verification", {})
        if isinstance(snapshot.get("verification"), dict)
        else {}
    )
    memory = snapshot.get("memory", {}) if isinstance(snapshot.get("memory"), dict) else {}
    comparison = (
        snapshot.get("adapter_comparison", {})
        if isinstance(snapshot.get("adapter_comparison"), dict)
        else {}
    )
    action = (
        snapshot.get("next_human_action", {})
        if isinstance(snapshot.get("next_human_action"), dict)
        else {}
    )
    blockers = snapshot.get("blockers", []) if isinstance(snapshot.get("blockers"), list) else []

    renderer.panel(
        "Dashboard",
        summary_table_lines(
            [
                ("project", project.get("name") or "unknown"),
                ("profile", project.get("profile") or "none"),
                ("runs", runs.get("total", 0)),
                ("current", current.get("run_id") or "none"),
            ]
        ),
    )

    renderer.section(
        "Current run",
        summary_table_lines(
            [
                ("status", current.get("status") or "none"),
                ("task", compact_text(current.get("task"), limit=90) or "none"),
                ("pack", current.get("pack") or "none"),
                ("checks", len(current.get("success_checks") or [])),
            ]
        ),
    )

    run_items = runs.get("items", []) if isinstance(runs.get("items"), list) else []
    run_rows = []
    for run in run_items[:5]:
        if isinstance(run, dict):
            marker = "*" if run.get("current") else "-"
            run_rows.append(
                [
                    marker,
                    str(run.get("run_id") or ""),
                    str(run.get("status") or ""),
                    compact_text(run.get("task"), limit=80),
                ]
            )
    renderer.table("Recent runs", ["", "Run", "Status", "Task"], run_rows or [["-", "none", "", ""]])

    renderer.section(
        "Verification",
        summary_table_lines(
            [
                ("status", verification.get("status") or "not run"),
                ("risk", verification.get("risk") or "unknown"),
                ("checks", f"{verification.get('checks_passed') or 0}/{verification.get('checks_total') or 0}"),
            ]
        ),
    )
    renderer.section(
        "Memory",
        summary_table_lines(
            [
                ("durable", f"{memory.get('durable_items') or 0} facts"),
                (
                    "proposals",
                    f"{memory.get('pending', 0)} pending, "
                    f"{memory.get('promoted', 0)} promoted, "
                    f"{memory.get('rejected', 0)} rejected",
                ),
            ]
        ),
    )
    renderer.section(
        "Next human action",
        summary_table_lines(
            [
                ("action", action.get("id") or "none"),
                ("command", action.get("command") or "none"),
                ("why", compact_text(action.get("why"), limit=100) or "none"),
            ]
        ),
    )
    if blockers:
        renderer.section("Blockers", [f"- {blocker}" for blocker in blockers])
    if not details:
        return

    attempt_items = attempts.get("items", []) if isinstance(attempts.get("items"), list) else []
    attempt_rows = []
    for attempt in attempt_items[:10]:
        if isinstance(attempt, dict):
            attempt_rows.append(
                [
                    str(attempt.get("id") or ""),
                    str(attempt.get("adapter") or ""),
                    str(attempt.get("status") or ""),
                    compact_text(attempt.get("summary"), limit=80),
                ]
            )
    renderer.table(
        "Attempts",
        ["Attempt", "Adapter", "Status", "Summary"],
        attempt_rows or [["none", "", "", ""]],
    )
    proposals = (
        memory.get("proposal_rows", []) if isinstance(memory.get("proposal_rows"), list) else []
    )
    proposal_rows = []
    for proposal in proposals[:10]:
        if isinstance(proposal, dict):
            proposal_rows.append(
                [
                    str(proposal.get("id") or ""),
                    str(proposal.get("status") or ""),
                    str(proposal.get("category") or ""),
                    compact_text(proposal.get("text"), limit=80),
                ]
            )
    if proposal_rows:
        renderer.table("Proposal rows", ["ID", "Status", "Category", "Text"], proposal_rows)

    groups = comparison.get("groups", []) if isinstance(comparison.get("groups"), list) else []
    comparison_rows = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        cost = group.get("cost", {}) if isinstance(group.get("cost"), dict) else {}
        comparison_rows.append(
            [
                str(group.get("adapter") or "unknown"),
                str(group.get("record_count", 0)),
                average_text(group.get("duration_seconds")),
                average_text(group.get("attempt_count")),
                average_text(group.get("total_tokens")),
                average_text(group.get("patch_size_bytes")),
                str(cost.get("known_count", 0)),
            ]
        )
    renderer.table(
        "Adapter comparison",
        ["Adapter", "Records", "Duration avg", "Attempts avg", "Tokens avg", "Patch avg", "Cost known"],
        comparison_rows or [["none", str(comparison.get("record_count", 0)), "", "", "", "", ""]],
    )
    renderer.section("Blockers", [f"- {blocker}" for blocker in blockers] or ["- none"])
