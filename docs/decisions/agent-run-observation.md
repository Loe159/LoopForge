# Agent output alongside the interactive terminal

The run view and the harness terminal observe the **same execution**. LoopForge
does not start a second agent to obtain a transcript. Interactive mode remains
the default where a terminal launcher is available; `--execution-mode headless`
continues to work.

## Transport by harness

| Harness | Interactive observation | Headless observation | Alternatives considered |
| --- | --- | --- | --- |
| Codex | Session/tool hooks, plus public message/reasoning entries from the exact transcript reported by the hook | `exec --json` | App Server is a richer integration but would also introduce server ownership, session attachment and approval routing. Hooks retain the existing terminal workflow. |
| Claude Code | Session/tool hooks, plus text/thinking blocks from the exact session transcript | `-p --verbose --output-format stream-json` | Tool hooks alone omit the conversation; the Agent SDK would replace the existing CLI process contract. |
| Kilo Code | Local plugin subscribing to `message.part.updated`, scoped to the session captured by `chat.message` | `run --format json --thinking` | A server subscription would require managing an additional server connection. |
| OpenCode | Same documented plugin event interface as Kilo (V1 plugin API) | `run --format json --thinking` | ACP/server APIs are viable for a future first-class session controller. OpenCode V2 plugins have a different API and are not covered by this V1 bridge. |
| Aider | No interactive adapter contract in LoopForge; existing automatic headless fallback | Readable text with `--no-pretty`, preserving all lines | Chat/LLM history files and Python integration exist, but do not provide the same stable CLI tool-event contract. No fabricated reasoning/tool classification. |
| mini-SWE-agent | No interactive adapter contract in LoopForge; existing automatic headless fallback | Sanitized text from the configured command | Native trajectories and Python agent subclassing exist; trajectory shapes vary with model and version. A versioned Python integration would be needed for reliable live typed events. |

Only reasoning actually exposed by a harness is displayed. Encrypted reasoning,
signatures and redacted thinking blocks are never interpreted or displayed.

## Runtime behavior

- The native terminal retains input, approvals and its full interface.
- Run-local observation configuration is passed to that process only. Global
  and project harness configuration files are not edited. No extra network
  service or package dependency is installed.
- Codex's hook trust checks remain enabled. When required, review the LoopForge
  observation hooks using `/hooks` inside Codex. The hook command is stable
  across runs; its destination is supplied through run-scoped environment values.
- Explicit Claude `--settings` are extended in a run-local copy. Existing hooks
  and permission settings are preserved; the source file is not edited. If the
  settings cannot be read, the original command remains in use and the journal
  explains the unavailable observation.
- Hooks return success without emitting decisions, permissions or model context.
- Kilo/OpenCode plugin listeners never change tool arguments or results.
- Public native messages augment tool hooks because tool hooks alone cannot
  provide a full conversation. Transcript lookup follows the path reported by
  the exact session; it never scans other conversations. Supported roots are
  `~/.codex/sessions` and `~/.claude/projects`. Custom roots and changed transcript
  schemas may yield tool events without message/reasoning content. Codex itself
  documents that its transcript schema is not a stable hook API.
- If hooks/plugins are disabled, untrusted or unsupported, the journal reports
  the absence of events and the terminal remains usable. It does not display
  terminal repaint bytes as agent messages.

## Artifacts and presentation

`adapter.stdout` retains the raw terminal capture for diagnostics.
`agent-transcript.log` holds the readable journal. Run-specific observation
spools retain bounded native hook/plugin records under `observation-*` in the
attempt/stage artifact directory. These are local agent output, not trusted
workflow evidence or approval receipts.

The run view prefers the readable journal, refreshes it as events arrive, shows
its latest bounded portion, and avoids displaying the same event again from
the operation history. Headers distinguish reasoning, messages, calls and tool
results; indentation preserves their contents. Text is rendered literally,
terminal control sequences are removed and recognizable secrets are redacted
by the existing adapter boundary. Native/raw artifacts can still contain
sensitive data and have the same local-only status as existing adapter output.

Native event capture and the readable journal are bounded. The current native
transcript reader scans at most 1 MiB per observation. Headless UTF-8 decoding
is incremental; partial JSON lines are buffered and oversized records bounded.
Final stage artifacts are extracted separately from Claude/Kilo/OpenCode event
streams, preserving the existing artifact validation and approval boundaries.

## Compact run narrative

The run view now uses incremental disclosure widgets within the existing
Textual renderer. Agent messages use primary text and spacing; reasoning is
secondary; tools occupy one quiet line with a status marker, their native name
(or `Shell` for command execution), and a short command/path preview. Click or
focus with Tab and press Enter to inspect arguments, output and exit code.
Opening details pauses tail following. Expansion and focus survive updates.

Native tool IDs are retained as an escaped `Call ID` metadata line in
LoopForge's readable blocks, across hooks, JSON event projection, subprocess
streaming and artifact reopening. The UI consumes this owned journal format,
not ANSI terminal output, hides the metadata, and replaces the corresponding
tool entry. Parallel same-name calls remain distinct. Legacy journals without
IDs only combine an unambiguous pending call with a matching command/name.
Missing results remain explicitly unknown once the operation stops; no success
is inferred. Raw artifacts and execution modes are unchanged.

The engine's stage-completion event and the foreground controller's completion
event remain in the operation history, but produce one completion receipt per
operation in the run narrative. Separate operations retain separate receipts.

This follows the progressive disclosure found in
[Claude Code's verbose transcript](https://code.claude.com/docs/en/interactive-mode)
and [OpenCode's tool-details toggle](https://opencode.ai/docs/tui/#details).
Regression coverage lives in `tests/test_run_transcript_ui.py`: native/hook and
legacy updates, concurrent calls, failed exits, duplicate results, completion
receipts, literal text, keyboard/mouse disclosure, stopped spinners, ASCII and
60-column layout. The existing full run-view streaming/scrolling test also
passes its assertions (executor shutdown still times out on this environment).

## Validation in this workspace

- 92 focused transcript, disclosure-widget, presentation, CLI-boundary and terminal integration
  tests pass, including the existing subprocess streaming tests.
- The generated plugin was executed with Node against representative native
  callbacks; session filtering and reasoning delivery passed.
- Python compilation and whitespace checks on the changed files pass when the
  repository's existing CRLF endings are recognized.
- The full `python -m unittest` run is not green: existing action-registry and
  Windows-path assumptions fail here, and Textual test executor shutdown hangs
  under this Python 3.14 environment. The focused run-view test completed its
  assertions but timed out during shutdown. Unrelated files were not repaired.
- No paid/live agent session or actual Windows terminal was launched during
  validation. The harness integrations are verified with protocol fixtures;
  hook/plugin availability still depends on the installed harness version.

## Sources checked

- [Codex JSON event stream](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex hook trust, fields and transcript caveat](https://learn.chatgpt.com/docs/hooks)
- [Claude programmatic output](https://code.claude.com/docs/en/headless)
- [Claude hooks](https://code.claude.com/docs/en/hooks)
- [Kilo plugin lifecycle and event bus](https://kilo.ai/docs/automate/extending/plugins)
- [Kilo configuration](https://kilo.ai/docs/code-with-ai/platforms/cli)
- [OpenCode V1 plugin events](https://dev.opencode.ai/docs/plugins/)
- [Aider scripting](https://aider.chat/docs/scripting.html)
- [mini-SWE-agent trajectories](https://mini-swe-agent.com/latest/reference/agents/default/)
