# Run observation contracts

Audited against the LoopForge observation/adapter code on 2026-10-20. Fixtures
in `tests/fixtures/run_observation/native_events.json` are synthetic public
protocol examples, not recordings or claims of installed harness versions.

| Source | Public identity | Allowed display evidence | Authority |
| --- | --- | --- | --- |
| Codex JSON | item id / call id | message, reasoning, command, MCP, search, TODO, declared file change | harness claim |
| Claude JSON | tool_use id / tool_result tool_use_id | public text/thinking, tool start/result | harness claim |
| Kilo / OpenCode JSON | part id / callID | public text/reasoning, tool state | harness claim |
| Codex / Claude hooks | exact session_id, tool_use_id | tool start/result, public messages | harness claim |
| Aider / mini-SWE text | local observation order only | literal sanitized output, no inferred tools | harness claim |
| Engine run state | run id, candidate_revision, stage, attempt | lifecycle, blockers, allowed actions | engine |
| Validators / receipts | artifact digest, candidate revision | contract results, deterministic checks, human decision | named validator / receipt |

Canonical attempt artifacts are `attempts/attempt-NNN/`. Read-only execution
artifacts are `artifacts/stages/{research,plan,review}/`; earlier sessions are
retained below the corresponding `sessions/` directory. Relative session
paths are UI selection identities, never workflow retargeting commands.

The durable observation store has eight 128 KiB segments per session (1 MiB
local retention), an atomic index, monotonic event order, and a 24 KiB event
budget. Readers request at most 500 events per page and can request earlier
pages using the first retained order. Dropped segments remain explicit in
index metadata. Legacy journals remain bounded fallbacks and never imply a
complete native transcript. Optional data is omitted; missing tool completion
is unknown after session end, never inferred success. Read/search categories
come only from explicit native tool names/types, not arbitrary shell text.

Prompt and output contents are untrusted. Display uses existing redaction and
terminal-control sanitation. References remain confined to the selected run;
symlinks and traversal are refused. Event source is assigned by capture code;
an agent-provided `source=engine` cannot grant verification authority.
