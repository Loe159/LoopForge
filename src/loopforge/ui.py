"""Terminal rendering helpers for LoopForge."""

from __future__ import annotations

import importlib.util
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any, TextIO

from loopforge.engine import GuidedAction, profile_permission_lines


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

    def __init__(self, output: TextIO, *, mode: str = "auto", theme: str = "default") -> None:
        self.output = output
        self.mode = mode
        self.theme = theme
        self.rich_available = importlib.util.find_spec("rich") is not None
        self.console = None
        self.use_rich = False
        self.set_mode(mode)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        auto_rich = (
            mode == "auto"
            and self.rich_available
            and hasattr(self.output, "isatty")
            and self.output.isatty()
            and os.environ.get("NO_COLOR") is None
        )
        self.use_rich = mode == "rich" and self.rich_available or auto_rich
        if self.use_rich:
            from rich.console import Console

            self.console = Console(
                file=self.output,
                force_terminal=True,
                color_system="standard",
                no_color=False,
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
            return str(path.resolve().relative_to(project_dir.resolve()))
        except (OSError, ValueError):
            pass
    return str(path)


def compact_text(value: object, *, limit: int = 96) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


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
    action = guidance.recommended_actions[0] if guidance.recommended_actions else None
    lines: list[str] = []
    lines.extend(action_lines(action))
    lines.append("")
    lines.append(f"project: {result.project_dir.name}")

    if not result.initialized:
        lines.extend(
            [
                "state: not initialized",
                f"next step: {result.next_step}",
            ]
        )
        if details:
            lines.append(f"config: {result.config_path}")
        lines.extend(blockers_lines(result.blockers))
        return lines

    config = result.config or {}
    lines.extend(
        [
            "state: initialized",
            f"profile: {config.get('profile')}",
        ]
    )

    if result.run is None:
        lines.append(f"current run: {config.get('current_run_id') or 'none'}")
        if result.run_dir is not None:
            lines.append(f"run directory: {result.run_dir}")
        lines.append(f"next step: {result.next_step}")
        lines.extend(blockers_lines(result.blockers))
        if details:
            lines.extend(_status_detail_lines(result))
        return lines

    run = result.run
    attempts = run.get("attempt_count", len(run.get("attempts", [])))
    lines.extend(
        [
            f"current run: {run.get('run_id')}",
            f"task: {compact_text(run.get('task'), limit=120)}",
            f"loop status: {run.get('status')}",
            f"attempts: {attempts}",
            f"pack: {run.get('pack')}",
        ]
    )
    if result.loop_contract is not None:
        lines.append(f"loop contract: {result.loop_contract.get('status')}")
        lines.append(f"success checks: {len(result.loop_contract.get('success_checks', []))}")
    if result.verification is not None:
        verification = result.verification
        lines.append(f"verification: {verification.get('status', 'unknown')}")
        lines.append(
            "pack checks: "
            f"{verification.get('checks_passed', 0)}/{verification.get('checks_total', 0)}"
        )
    else:
        lines.append("verification: not run")
    if result.memory is not None:
        lines.append(f"durable memory: {result.memory.get('durable_items', 0)} items")
        lines.append(f"memory proposals: {result.memory.get('pending', 0)} pending")
    _append_artifact_attention(lines, result)
    lines.append(f"next step: {result.next_step}")
    lines.extend(blockers_lines(result.blockers))
    if details:
        lines.extend(_status_detail_lines(result))
    return lines


def _append_artifact_attention(lines: list[str], result: Any) -> None:
    native = result.native_artifacts or {}
    legacy = result.legacy_artifacts or {}
    if native.get("status") not in {None, "complete"}:
        lines.append(
            f"native artifacts: {native.get('status')} ({native.get('present')}/{native.get('total')})"
        )
    if legacy.get("status") not in {None, "valid"}:
        lines.append(f"legacy artifacts: {legacy.get('status')}")
        errors = legacy.get("errors", [])
        for error in errors:
            if isinstance(error, dict):
                message = error.get("message", error)
                lines.append(f"- {message}")
            else:
                lines.append(f"- {error}")


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

    lines.extend(_native_artifact_lines(result.native_artifacts))
    lines.extend(_loop_contract_lines(result.loop_contract))
    lines.extend(_legacy_artifact_lines(result.legacy_artifacts))
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


def _legacy_artifact_lines(state: dict[str, object] | None) -> list[str]:
    if state is None:
        return []
    lines = [
        f"legacy artifacts: {state['status']}",
        f"legacy issue: {state.get('issue') or 'none'}",
        f"legacy artifact directory: {state.get('artifact_dir') or 'none'}",
    ]
    errors = state.get("errors", [])
    if errors:
        lines.append("legacy artifact notes:")
        for error in errors:
            if isinstance(error, dict):
                artifact = error.get("artifact", "*")
                rule = error.get("rule", "note")
                message = error.get("message", error)
                lines.append(f"- {artifact} {rule}: {message}")
            else:
                lines.append(f"- {error}")
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
    renderer.panel("LoopForge status", lines)


def render_dashboard(renderer: TerminalRenderer, snapshot: dict[str, Any]) -> None:
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
        "LoopForge dashboard",
        [
            f"project: {project.get('name') or 'unknown'}",
            f"initialized: {project.get('initialized')}",
            f"profile: {project.get('profile') or 'none'}",
            f"runs: {runs.get('total', 0)}",
        ],
    )

    renderer.section(
        "Current loop",
        [
            f"run id: {current.get('run_id') or 'none'}",
            f"task: {compact_text(current.get('task'), limit=120) or 'none'}",
            f"status: {current.get('status') or 'none'}",
            f"pack: {current.get('pack') or 'none'}",
            f"loop contract: {current.get('loop_contract_status') or 'none'}",
            f"success checks: {len(current.get('success_checks') or [])}",
            f"next step: {current.get('next_step') or 'none'}",
        ],
    )

    run_items = runs.get("items", []) if isinstance(runs.get("items"), list) else []
    run_rows = []
    for run in run_items[:10]:
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
    renderer.table("Run list", ["", "Run", "Status", "Task"], run_rows or [["-", "none", "", ""]])

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

    renderer.section(
        "Verification",
        [
            f"status: {verification.get('status') or 'not run'}",
            f"risk: {verification.get('risk') or 'unknown'}",
            f"checks: {verification.get('checks_passed') or 0}/{verification.get('checks_total') or 0}",
            f"patch size bytes: {verification.get('patch_size_bytes') or 'unknown'}",
        ],
    )
    renderer.section(
        "Memory proposals",
        [
            f"durable items: {memory.get('durable_items') or 0}",
            (
                "proposals: "
                f"{memory.get('pending', 0)} pending, "
                f"{memory.get('promoted', 0)} promoted, "
                f"{memory.get('rejected', 0)} rejected"
            ),
        ],
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
    renderer.section(
        "Next human action",
        [
            f"id: {action.get('id') or 'none'}",
            f"label: {action.get('label') or 'none'}",
            f"command: {action.get('command') or 'none'}",
            f"do command: {action.get('do_command') or 'none'}",
            f"requires confirmation: {action.get('requires_confirmation')}",
            f"why: {action.get('why') or 'none'}",
        ],
    )
    renderer.section("Blockers", [f"- {blocker}" for blocker in blockers] or ["- none"])
