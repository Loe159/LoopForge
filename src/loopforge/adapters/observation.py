"""Run-scoped observation alongside an interactive harness terminal.

Hooks identify the exact session; only its public message fields are read from
the native transcript. Tool events come from hooks. Kilo/OpenCode use their
plugin event bus directly. Terminal repaint bytes never enter this journal.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable
from uuid import uuid4

from loopforge.adapters.local_implementation_adapter import (
    adapter_event_lines, observable_stream_block, observable_stream_text,
)
from loopforge.adapters.commands import _without_options


TRANSCRIPT_NAME = "agent-transcript.log"
MAX_BYTES = 131_072


def retire_terminal_transcript(directory: Path) -> None:
    """Keep a prior terminal journal from masking a headless retry of a stage."""

    journal = directory / TRANSCRIPT_NAME
    if journal.is_file() or journal.is_symlink():
        journal.replace(directory / f"previous-agent-transcript-{uuid4().hex}.log")


def _claude_session_settings(command: tuple[str, ...], hooks: dict, workspace: Path) -> dict:
    """Extend explicit settings without changing any permissions or user hooks."""

    settings: dict = {}
    for index, argument in enumerate(command):
        if argument.startswith("--settings="):
            source = argument.split("=", 1)[1]
        elif argument == "--settings" and index + 1 < len(command):
            source = command[index + 1]
        else:
            continue
        if source.lstrip().startswith("{"):
            raw = source
        else:
            with (workspace / source).open(encoding="utf-8") as handle:
                raw = handle.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Claude settings exceed the settings size limit")
        settings = json.loads(raw)
        if not isinstance(settings, dict):
            raise ValueError("Claude settings must be an object")
    existing = settings.setdefault("hooks", {})
    if not isinstance(existing, dict):
        raise ValueError("Claude hooks must be an object")
    for name, groups in hooks.items():
        previous = existing.setdefault(name, [])
        if not isinstance(previous, list):
            raise ValueError("Claude hook matchers must be a list")
        previous.extend(groups)
    return settings


_EVENT_PLUGIN = r'''
import { appendFileSync, statSync } from "node:fs";
export const LoopForgeObservation = async ({ directory }) => {
  const expected = __WORKSPACE__;
  const target = __TARGET__;
  let session;
  const write = (event) => {
    try {
      const line = JSON.stringify(event) + "\n";
      let size = 0;
      try { size = statSync(target).size; } catch {}
      if (size + Buffer.byteLength(line) <= 131072) appendFileSync(target, line, { mode: 0o600 });
    } catch {} // Observation never changes tool execution.
  };
  return {
    "chat.message": async (input) => { if (directory === expected) session ??= input.sessionID; },
    event: async ({ event }) => {
      if (directory !== expected) return;
      const part = event.properties?.part;
      if (event.type !== "message.part.updated" || !part || part.sessionID !== session) return;
      if (["text", "reasoning"].includes(part.type) && !part.time?.end) return;
      if (!["text", "reasoning", "tool"].includes(part.type)) return;
      write({ type: part.type === "tool" ? "tool_use" : part.type, part });
    },
  };
};
'''


class TerminalObservation:
    def __init__(self, command: tuple[str, ...], workspace: Path, directory: Path,
                 callback: Callable[[str, bytes], None] | None):
        self.command = command
        self.workspace = workspace.resolve()
        self.directory = directory.resolve()
        self.callback = callback
        self.environment: dict[str, str] = {}
        self.adapter = Path(command[0]).stem.casefold() if command else ""
        self.active = self.adapter in {"codex", "claude", "claude-code", "kilo", "opencode"}
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.offset = 0
        self.pending = b""
        self.native_path: Path | None = None
        self.native_offset = 0
        self.native_pending = b""
        self.state: dict = {}
        self.written = 0
        self.received = False
        self.session: str | None = None
        self.last_message = ""
        self.truncated = False

    def prepare(self) -> None:
        if not self.active:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        # A fresh directory avoids replaying a previous invocation of a stage.
        self.spool = Path(tempfile.mkdtemp(prefix="observation-", dir=self.directory))
        self.events_path = self.spool / "harness-events.jsonl"
        self.journal = self.directory / TRANSCRIPT_NAME
        if self.journal.is_symlink():
            raise ValueError("Agent transcript must not be a symlink")
        self.journal.write_text("", encoding="utf-8")
        if self.adapter in {"kilo", "opencode"}:
            plugin = self.spool / "observe.mjs"
            plugin.write_text(_EVENT_PLUGIN.replace("__WORKSPACE__", json.dumps(str(self.workspace)))
                              .replace("__TARGET__", json.dumps(str(self.events_path))), encoding="utf-8")
            variable = "KILO_CONFIG_CONTENT" if self.adapter == "kilo" else "OPENCODE_CONFIG_CONTENT"
            self.environment[variable] = json.dumps({"plugin": [plugin.as_uri()]})
        else:
            self.environment.update(LOOPFORGE_OBSERVATION_DIR=str(self.spool),
                                    LOOPFORGE_OBSERVATION_WORKSPACE=str(self.workspace))
            script = Path(__file__).with_name("observation_hook.py")
            argv = [sys.executable, str(script)]
            hook_command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
            hooks = {name: [{"hooks": [{"type": "command", "command": hook_command, "timeout": 3}]}]
                     for name in ("SessionStart", "PreToolUse", "PostToolUse", "Stop")}
            if self.adapter == "codex":
                options: list[str] = []
                for name, groups in hooks.items():
                    handler = groups[0]["hooks"][0]
                    value = '[{hooks=[{type="command",command=' + json.dumps(handler["command"]) + ',timeout=3}]}]'
                    options.extend(["-c", f"hooks.{name}={value}"])
                self.command = (self.command[0], *options, *self.command[1:])
            else:
                hooks["PostToolUseFailure"] = hooks["PostToolUse"]
                try:
                    settings = _claude_session_settings(self.command, hooks, self.workspace)
                except (OSError, ValueError, TypeError):
                    self.publish(["Observation unavailable: Claude session settings could not be extended.",
                                  "The terminal will use the original settings."])
                    return
                args = _without_options(self.command[1:], value_options={"--settings"})
                settings_path = self.spool / "claude-settings.json"
                from loopforge.engine.storage import DEFAULT_JSON_STORE
                DEFAULT_JSON_STORE.write_object(settings_path, settings)
                self.command = (self.command[0], "--settings", str(settings_path), *args)
        notice = "Waiting for harness events; the interactive terminal remains available."
        if self.adapter == "codex":
            notice += " If needed, review the LoopForge observation hooks with /hooks in Codex."
        self.publish([notice])

    def publish(self, lines: list[str]) -> None:
        if not lines:
            return
        text = "\n".join(lines) + "\n\n"
        safe = observable_stream_text(text, limit=8000) + "\n\n"
        data = safe.encode("utf-8")
        if self.written + len(data) > MAX_BYTES - 256:
            if self.truncated:
                return
            data = b"Observation limit reached; continue following the interactive terminal.\n\n"
            self.truncated = True
        try:
            if self.journal.is_symlink():
                return
            with self.journal.open("ab") as handle:
                handle.write(data)
        except OSError:
            return
        self.written += len(data)
        if self.callback is not None:
            self.callback("stdout", data)

    def start(self) -> None:
        if not self.active:
            return
        def follow() -> None:
            while not self.stop.wait(0.1):
                self.poll()
        self.thread = threading.Thread(target=follow, name="loopforge-observation", daemon=True)
        self.thread.start()

    def close(self) -> None:
        if not self.active:
            return
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2)
        # Drain the bounded files after exit, including bursts larger than one read.
        for _ in range(20):
            before = (self.offset, self.native_offset)
            self.poll()
            if before == (self.offset, self.native_offset):
                break
        if not self.received:
            self.publish(["No structured events received. See the interactive terminal;",
                          "check harness hook/plugin support or use headless mode."])

    def poll(self) -> None:
        try:
            if self.events_path.is_symlink():
                return
            with self.events_path.open("rb") as handle:
                handle.seek(self.offset)
                data = handle.read(min(65_536, max(0, MAX_BYTES - self.offset)))
                self.offset += len(data)
            self.pending += data
            while b"\n" in self.pending:
                line, self.pending = self.pending.split(b"\n", 1)
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(event, dict):
                    self.consume(event)
        except OSError:
            pass
        self.read_native_messages()

    def consume(self, event: dict) -> None:
        self.received = True
        if self.adapter in {"kilo", "opencode"}:
            self.publish(adapter_event_lines(event, self.state))
            return
        session = event.get("session_id")
        if not isinstance(session, str) or not session:
            return
        if self.session is None:
            self.session = session
        if self.session != session:
            return
        raw_path = event.get("transcript_path")
        if isinstance(raw_path, str) and self.native_path is None:
            path = Path(raw_path).resolve()
            # Never follow arbitrary paths from tool payloads. Only native session roots.
            root = Path.home() / (".codex/sessions" if self.adapter == "codex" else ".claude/projects")
            if path.is_relative_to(root.resolve()) and path.suffix == ".jsonl":
                self.native_path = path
        self.read_native_messages()
        kind = event.get("hook_event_name")
        tool = observable_stream_text(event.get("tool_name") or "tool")
        if kind == "PreToolUse":
            self.publish(observable_stream_block("Tool call · " + tool, event.get("tool_input"),
                                                 call_id=event.get("tool_use_id")))
        elif kind in {"PostToolUse", "PostToolUseFailure"}:
            failed = kind == "PostToolUseFailure"
            label = f"Tool result ({'failed' if failed else 'completed'}) · {tool}"
            self.publish(observable_stream_block(label, event.get("tool_response") or event.get("error"),
                                                 call_id=event.get("tool_use_id")))
        elif kind == "Stop":
            last = event.get("last_assistant_message")
            if isinstance(last, str) and last and last != self.last_message:
                self.publish(observable_stream_block("Agent message", last))
                self.last_message = last

    def read_native_messages(self) -> None:
        if self.native_path is None:
            return
        try:
            with self.native_path.open("rb") as handle:
                handle.seek(self.native_offset)
                data = handle.read(min(65_536, max(0, MAX_BYTES * 8 - self.native_offset)))
                self.native_offset += len(data)
            self.native_pending += data
            while b"\n" in self.native_pending:
                line, self.native_pending = self.native_pending.split(b"\n", 1)
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(event, dict):
                    continue
                if self.adapter == "codex":
                    payload = event.get("payload")
                    if event.get("type") != "event_msg" or not isinstance(payload, dict):
                        continue
                    label = {"agent_reasoning": "Reasoning", "agent_message": "Agent message"}.get(payload.get("type"))
                    if label:
                        value = payload.get("text") or payload.get("message")
                        self.publish(observable_stream_block(label, value))
                        if label == "Agent message":
                            self.last_message = value
                elif event.get("type") == "assistant" and isinstance(event.get("message"), dict):
                    message = event["message"]
                    content = message.get("content")
                    if isinstance(content, list):
                        visible = [block for block in content if isinstance(block, dict)
                                   and block.get("type") in {"text", "thinking"}]
                        self.publish(adapter_event_lines({"type": "assistant", "message": {"content": visible}}, self.state))
                        self.last_message = "\n".join(str(block.get("text") or "") for block in visible if block.get("type") == "text")
            if len(self.native_pending) > MAX_BYTES:
                self.native_pending = b""
        except OSError:
            pass
