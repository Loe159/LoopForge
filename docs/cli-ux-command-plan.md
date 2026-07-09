# LoopForge CLI UX Command Plan

This plan tracks command-by-command UX and design improvements for LoopForge's
human-facing CLI and interactive shell.

## Global Principle

Every command should show three things, in this order:

1. **Important state now**: what happened, what is ready, or what is blocked.
2. **Useful proof**: run id, status, generated file, count, risk, check, or short path.
3. **Next action**: one concrete command to run next.

Common design language:

- `green`: success or ready.
- `yellow`: attention or human action required.
- `red`: blocked or failed.
- `cyan`: command to run.
- `dim`: paths and secondary detail.
- Default output should be short; deeper details belong behind `--details`.
- Use loaders for commands that scan, execute adapters, generate artifacts, or read many runs.

## Top-Level Commands

### `loopforge init`

Important screen info:

- Project initialized, repaired, or already ready.
- Active profile.
- Run root.

UX improvements:

- If already initialized, say `Project already ready` rather than sounding like nothing happened.
- If repaired, list only repaired items.
- End with `loopforge run --task "..."`.

Design:

```text
LoopForge project ready
project   LoopForge
profile   supervised
runs      C:\...\LoopForge\runs\LoopForge

Next
loopforge run --task "Describe the task"
```

### `loopforge run`

Important screen info:

- Run created.
- Goal.
- Run id.
- Selected pack.
- Loop contract status.
- Next action.

UX improvements:

- Keep the loader and guide behavior.
- If `--task` is absent in a TTY, ask step by step:
  - task;
  - success check;
  - optional profile or pack;
  - rubric when subjective.
- If no success check is present, show a short warning, not a wall of text.

Design:

```text
Run created
goal      Improve CLI status output
run       run-...
pack      python
contract  draft

Next
loopforge continue
```

### `loopforge status`

Important screen info:

- Current state.
- Blocker or next action.
- Active run.
- Verification state.

UX improvements:

- Default output should be 6-8 high-signal lines.
- Move paths, artifacts, memory, and policy into `--details`.
- Consider a short `statusline` variant later.

Design:

```text
Current loop
status    ready_for_verification
run       run-...
task      Improve CLI output
checks    2 success checks
verify    not run

Next
loopforge verify
```

### `loopforge guide`

Important screen info:

- Why LoopForge recommends the next action.
- One priority action.
- Blocking reasons, if any.

UX improvements:

- Do not repeat the full status.
- Structure as:
  - You are here;
  - Why;
  - Do this.
- Show extra actions only as secondary `Also useful`.

Design:

```text
You are here
The run is ready for verification.

Why
The workspace changed and no patch has been verified yet.

Do this
loopforge verify
```

### `loopforge dashboard`

Important screen info:

- Overall operator health: runs, verification, memory, metrics.
- Current run first.

UX improvements:

- Make default output less verbose.
- Group sections:
  - Project;
  - Current run;
  - Verification;
  - Recent runs;
  - Next human action.
- Show top 5 runs by default.

Design:

- Compact sections.
- Short tables.
- No repeated internal state unless `--details` exists later.

### `loopforge runs`

Important screen info:

- Known runs.
- Current run marker.
- Status, short task, updated time.

UX improvements:

- Add summary header:
  - total runs;
  - current run;
  - latest status.
- If no runs exist, show `No runs yet` and next command.

Design:

```text
Runs
current  run-...  ready_for_verification  Improve CLI output

Run                         Status                  Updated
* run-2026...               ready_for_verification  2026-...
  run-2026...               verified                2026-...
```

### `loopforge continue`

Important screen info:

- Contract validation or adapter attempt.
- Attempt id.
- Adapter.
- Result.
- Whether workspace changed.
- Next action.

UX improvements:

- Use loader when adapter runs.
- If validation only, say clearly that no adapter executed.
- On failure, show stderr tail and artifact path.
- On success, hide full profile text unless `--details`.

Design:

```text
Attempt completed
attempt   attempt-001
adapter   codex
changed   yes
status    completed

Next
loopforge verify
```

Failure:

```text
Attempt blocked
reason    Adapter reported blocked
stderr    attempts/attempt-001/adapter.stderr

Last stderr
> ...

Next
loopforge shell --command "/raw latest stderr"
```

### `loopforge verify`

Important screen info:

- Verification status.
- Patch path.
- Risk.
- Checks passed.
- Blockers.

UX improvements:

- Use loader.
- If passing, show a clear `Verified`.
- If failing, show the failed check and diagnostic command.
- Hide detailed risk policy unless `--details`.

Design:

```text
Verification failed
checks    3/4 passed
risk      medium
patch     verification/complete.patch

Blocking check
unit-tests failed

Next
Inspect verification.md, fix the diagnostic, then run:
loopforge verify
```

### `loopforge learn`

Important screen info:

- Proposals created, promoted, rejected, pending.
- Proposal path.
- Next action.

UX improvements:

- If run without `--approve`, say explicitly that nothing was promoted.
- If pending proposals exist, suggest `loopforge learn --approve`.
- Mention `--confirm` only when strict profile requires it.

Design:

```text
Memory proposals ready
pending   2
promoted  0
rejected  1
file      memory-proposals.json

Next
Review proposals, then run:
loopforge learn --approve
```

### `loopforge pack list`

Important screen info:

- Available packs.
- Source.
- Detected pack, if available.

UX improvements:

- Keep a short table by default.
- Add a `kind` column: bundled, local, override.
- Mark the detected pack.

Design:

```text
Project packs
* generic-code   Default code changes      bundled
  python         Python packages/tests     bundled
  custom         Custom project pack       local override
```

### `loopforge pack detect`

Important screen info:

- Selected pack.
- Score or detection reason.
- Source.

UX improvements:

- Explain why selected instead of only printing a score.
- End with `loopforge run --pack <name> --task "..."`.

Design:

```text
Detected pack
pack    node
score   40
why     package.json found
source  .loopforge/packs/node/pack.json
```

### `loopforge metrics record`

Important screen info:

- Metrics record written or refused.
- Run id.
- Known and unknown fields.

UX improvements:

- Keep default output short.
- Say `not reported` for missing values, not zero.
- If no run exists, suggest `loopforge run`.

Design:

```text
Metrics recorded
run       run-...
duration  42s
tokens    not reported
cost      not reported
file      metrics/record.json
```

### `loopforge metrics summarize`

Important screen info:

- Record count.
- Useful averages.
- Unknown counts.
- Simple signal quality warning.

UX improvements:

- Default to an operator summary.
- Put per-run table behind `--details` or keep it for `json`/`csv`.
- Warn when too many values are unknown.

Design:

```text
Metrics summary
records   8
duration  avg 41s, 2 unknown
attempts  avg 1.4
cost      0 known, 8 unknown

Signal
Cost and token reporting are incomplete.
```

### `loopforge version`

Important screen info:

- LoopForge version.
- Python/runtime.
- Useful paths.

UX improvements:

- Keep default compact.
- Add `--details` later for full diagnostic output.
- Make text output suitable for issue reports.

Design:

```text
LoopForge 0.1.0
python    3.13.13
platform  Windows
home      C:\...\LoopForge
config    .loopforge/config.json
```

### `loopforge help`

Important screen info:

- Main commands.
- Workflow.
- Examples.

UX improvements:

- Replace raw argparse feel with grouped help.
- Groups:
  - Start;
  - Work loop;
  - Inspect;
  - Configure;
  - Automation.
- Keep full argparse-style help available via `--help` or future `help --all`.

Design:

```text
LoopForge
Portable agentic workflow loops.

Start
  init      Prepare this project
  run       Create a bounded run

Work
  status    See where you are
  continue  Execute or validate next attempt
  verify    Generate patch and run checks
```

### `loopforge completion`

Important screen info:

- Completion script on stdout.
- Installation examples in help only.

UX improvements:

- Keep stdout as pure script.
- Add better examples to `loopforge completion --help`.

Design:

```text
Examples
  loopforge completion powershell > loopforge-completion.ps1
```

## Interactive Shell

The shell should be the smoothest LoopForge experience, not just a slash-command
catalog.

### Shell entry screen

Important screen info:

- Project.
- Current run.
- Status.
- Next action.
- Adapter.

UX improvements:

- On startup, show a short home panel.
- If not initialized, suggest `/init`.
- If initialized without a run, suggest `/run`.

Design:

```text
LoopForge shell
project   LoopForge
run       run-... ready_for_verification
adapter   codex

Next
/do verify
```

Prompt idea:

```text
loopforge ready_for_verification >
```

Blocked prompt:

```text
loopforge blocked >
```

### `/status`

Important screen info:

- Same as top-level `status`, but with interactive commands.

UX improvements:

- Short by default.
- Suggest `/next`, `/do <id>`, `/plan`, or `/raw latest stderr`.

Design:

- Compact panel.
- Status-colored badge.

### `/guide`, `/next`, `/why`

Important screen info:

- One action and one reason.

UX improvements:

- `/next`: just the next command.
- `/why`: why that command is recommended.
- `/guide`: short combined view.

Design:

```text
Next
/do verify

Why
Workspace changed and verification has not run.
```

### `/actions` and `/do`

Important screen info:

- Available actions.
- Executed action.

UX improvements:

- `/actions`: short table with id, label, confirmation.
- `/do`: before mutating work, explain what will happen.
- If confirmation is required, prompt clearly.

Design:

```text
Actions
verify   Generate patch and run checks   safe
learn    Propose memory updates          safe
```

### `/run`, `/new`, `/fork`

Important screen info:

- New run created.
- Task.
- Contract status.
- Next action.

UX improvements:

- Make `/run` conversational:
  - task;
  - success checks;
  - rubric if subjective;
  - adapter or pack if needed.
- `/new` stays a natural alias.
- `/fork` shows what is inherited from the previous run.

Design:

- Match top-level `run` style.
- End with `/continue`.

### `/continue`

Important screen info:

- Validation or attempt.
- Attempt id.
- Result.
- Next action.

UX improvements:

- Use loader.
- Stream adapter output live, then summarize compactly.
- On failure, suggest `/raw latest stderr`.

Design:

- Status badge.
- Last stderr lines in a red or dim block.

### `/verify`

Important screen info:

- Checks.
- Patch.
- Risk.
- Next action.

UX improvements:

- Use loader.
- On success, suggest `/review` or `/learn`.
- On failure, suggest `/diff`, `/raw`, or `/export plan`.

Design:

- Short check table.
- Colored global status.

### `/learn`, `/approve`, `/memory`, `/memories`

Important screen info:

- Pending, promoted, rejected proposals.
- Durable memory item count.

UX improvements:

- `/learn` proposes only.
- `/approve` confirms promotion clearly.
- `/memory` is summary.
- `/memories` is detailed view.
- Add a readable proposal review step before approval.

Design:

```text
Memory
durable   12 facts
pending   3 proposals

Next
/approve
```

### `/runs`, `/resume`, `/archive`

Important screen info:

- Runs.
- Current run.
- Archive status.

UX improvements:

- `/runs`: scannable table.
- `/resume`: after switching, show short status of resumed run.
- `/archive`: say artifacts are kept.

Design:

- `*` marks current run.
- Color status values.

### `/plan`, `/tasks`, `/ps`

Important screen info:

- Current plan or contract.
- Attempts.
- Next task.

UX improvements:

- `/plan`: human contract, success checks, allowed tools.
- `/tasks`: attempts plus next action.
- `/ps`: clearly say these are recorded attempts, not live processes.

Design:

- Tables.
- Success checks as checklist.

### `/diff`, `/review`, `/code-review`, `/security-review`, `/simplify`

Important screen info:

- Local changes.
- Risks.
- Recommendations.

UX improvements:

- `/diff`: summary before raw diff.
- `/review`: findings first, then tests.
- `/security-review`: only security-relevant evidence; do not invent.
- `/simplify`: cleanup opportunities only, no automatic refactor.

Design:

- Sections:
  - Changed files;
  - Risks;
  - Suggested next step.

### `/context`, `/mention`, `/add-dir`, `/compact`, `/copy`, `/export`

Important screen info:

- Active context.
- Mentioned files.
- Exported artifact.

UX improvements:

- `/context`: group by category.
- `/mention`: confirm file and size.
- `/add-dir`: warn if directory is large.
- `/compact`: show handoff path.
- `/copy` and `/export`: keep format and messages consistent.

Design:

```text
Context
project files   4 mentioned
extra dirs      1
scratch         present

Exported
compact.md
```

### `/raw`

Important screen info:

- Attempt.
- Stream.
- Requested content.

UX improvements:

- Limit huge output by default.
- Support clear patterns:
  - `/raw latest stderr`;
  - `/raw latest stdout`;
  - `/raw attempt-002 result`.
- If stream is empty, say `empty`.

Design:

- Header with source.
- Monospace content block.

### `/adapter`, `/adapters`

Important screen info:

- Current adapter.
- Supported adapters.
- Default args.

UX improvements:

- `/adapter` without args shows current adapter and example change.
- `/adapter codex -- -m gpt-5` confirms save.
- `/adapters` is a table.

Design:

```text
Adapter
current  codex
args     -m gpt-5

Change
/adapter local-adapter-fixture -- python script.py
```

### `/config`, `/debug-config`, `/doctor`

Important screen info:

- Active config.
- Environment problems.
- Fix command.

UX improvements:

- `/doctor`: ok/missing/fix.
- `/debug-config`: paths, env vars, config merge.
- `/config`: simple read; guided update.

Design:

```text
Check              Status   Fix
prompt_toolkit     ok
rich               ok
git                missing  install git
```

### `/permissions`, `/allowed-tools`, `/sandbox`

Important screen info:

- What is allowed.
- What needs confirmation.
- Sandbox limits.

UX improvements:

- Do not print full policy by default.
- Summarize:
  - filesystem;
  - network;
  - publication;
  - destructive actions.
- Suggest `/plan` for run-specific allowed tools.

Design:

- Badges: allowed, requires confirm, blocked.

### `/pack`, `/skills`, `/plugins`

Important screen info:

- Detected pack.
- Available skills.
- Plugin boundaries.

UX improvements:

- `/pack`: align with top-level `pack list/detect`.
- `/skills`: group by pack.
- `/plugins`: explain external connector limits.

Design:

- Short tables.
- Current pack marked `*`.

### `/branch`

Important screen info:

- Current git branch.
- Created branch, if any.

UX improvements:

- Before creation, show intended branch name.
- After creation, confirm.
- If not in a git repo, show fix.

Design:

```text
Git branch
current  main
created  codex/cli-ux
```

### `/stats`, `/usage`, `/cost`

Important screen info:

- Known values.
- Unknown values.

UX improvements:

- Say `not reported`, not zero.
- `/usage`: token data if available.
- `/cost`: cost data if available.
- `/stats`: local summary.

Design:

- Small tables.
- Unknown counts in yellow.

### `/theme`, `/tui`, `/statusline`, `/keymap`, `/vim`, `/title`

Important screen info:

- Updated preference.
- Current value.

UX improvements:

- If no argument, show current setting.
- After change, one-line confirmation.

Design:

```text
Theme set
theme  mono
```

### `/commands`, `/help`

Important screen info:

- Available commands.
- Useful groups.

UX improvements:

- `/commands`: grouped, not just alphabetic.
- `/commands all`: include unsupported commands.
- `/help <cmd>`: usage plus examples.

Design groups:

- Start.
- Work Loop.
- Review.
- Context.
- Settings.

### `/clear`, `/cd`, `/recap`, `/goal`, `/exit`, `/quit`

Important screen info:

- Immediate action result.

UX improvements:

- `/clear`: no extra text.
- `/cd`: show new project and short status.
- `/recap`: one useful line.
- `/goal`: current objective and success checks.
- `/exit` and `/quit`: exit cleanly, no ceremony.

Design:

- Strictly minimal.

## Implementation Priority

1. **Refactor common display helpers**
   - Add shared renderers such as `render_success`, `render_blocked`,
     `render_next`, and `render_summary_table`.

2. **Rework critical top-level commands**
   - `status`
   - `continue`
   - `verify`
   - `learn`
   - `runs`

3. **Rework discovery and operator commands**
   - `help`
   - `dashboard`
   - `pack`
   - `metrics`
   - `version`

4. **Rework shell experience**
   - Home panel.
   - Richer prompt.
   - Stronger `/next`.
   - Clearer `/do`.
   - Grouped `/commands`.

5. **Add UX tests**
   - Default output is short.
   - Next action is visible.
   - Blockers are visible.
   - JSON remains unchanged.
   - `--quiet` is genuinely quiet.

Core goal: each command should stop dumping internal state and instead become a
small operator scene: **where I am, what matters, what to do next**.
