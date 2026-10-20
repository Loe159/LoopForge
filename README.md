# LoopForge

LoopForge is a portable agentic workflow engine. It turns a task into a bounded
work loop with staged intake, read-only research and planning, gated
implementation, deterministic verification, explicit review, and local draft
publication preparation.

This repository starts from the reusable core of the ABL plugin workflow:
portable artifacts, patch generation, deterministic policy checks, bounded
process execution, local adapters, and metrics. The product direction is more
general and ergonomic: one engine, multiple project packs, explicit autonomy
profiles.

The [Run/Live TUI UX specification](docs/plans/2026-10-20-001-run-live-context-ux-plan.md) documents the approved redesign, harness observation sources, wireframes, data model, implementation plan, and test criteria. **Design approved; not implemented.**

## Installation

Requires Python 3.11+, Git, and internet access to GitHub and the Python
package index. On Linux/macOS, run from this repository:

```sh
sh install.sh
```

Or download and run the installer without cloning the repository:

```sh
curl -fsSL https://raw.githubusercontent.com/Loe159/LoopForge/master/install.sh -o /tmp/loopforge-install.sh
sh /tmp/loopforge-install.sh
```

The installer places LoopForge in `~/.local/share/loopforge/venv` and exposes
the command in `~/.local/bin`. If needed, it prints the line to add that
directory to your shell's `PATH`. No administrator access is required.
On distributions that package `venv` separately, install the Python venv
package first. `LOOPFORGE_PYTHON`, `LOOPFORGE_INSTALL_DIR`, and
`LOOPFORGE_BIN_DIR` override the interpreter, environment, and command directory.
An existing pip-generated LoopForge launcher, including a broken installation,
is backed up and replaced after the new installation succeeds. Unrecognized
commands are preserved. To install this checkout (including local fixes) rather
than GitHub master, run `LOOPFORGE_INSTALL_SOURCE="$PWD" sh install.sh`.

On Windows (or with an existing pipx installation on Linux/macOS):

```text
py -m pip install --user pipx
py -m pipx ensurepath
py -m pipx install "git+https://github.com/Loe159/LoopForge.git@master"
```

Use `python3` instead of `py` on Linux/macOS. Reopen your terminal after
`ensurepath` if the command is not yet available.

To update from any project directory:

```text
loopforge update
```

`loopforge update` and `/update` install the latest commit of GitHub `master`
into the Python environment running LoopForge, even when the package version
has not changed. They work with installed packages and editable installations,
without requiring a local checkout or changing local branches/files. Updating
an editable installation replaces it with a regular installation from `master`.
Restart running LoopForge sessions after updating. For local development,
keep using `python -m pip install -e .`; `loopforge install` reinstalls local
sources and requires a source checkout.

## MVP Shape

```text
loopforge init
loopforge run --task "..."
loopforge status
loopforge continue
loopforge verify
loopforge learn
loopforge guide
loopforge shell
```

For command discovery:

```text
loopforge --help
loopforge help run
loopforge version
loopforge runs --format json
loopforge completion powershell
```

`loopforge` opens the Textual TUI. `loopforge run --task "..."` or an approved
GitHub issue creates a run without prompting. With an active run and no new
source, `loopforge run` only reports status. The TUI guides these stages:

1. validate the goal and objective proof, then approve the task
   (`agent:approved` for GitHub issues, local confirmation for manual tasks);
2. invoke the read-only `researcher` and validate `research.md`;
3. invoke the read-only `planner`, validate `plan.md`, then approve the plan;
4. invoke the workspace-write `developer` with `loopforge continue`;
5. run deterministic verification with `loopforge verify`;
6. invoke the read-only `reviewer`, validate `review.md`, then explicitly
   approve the review;
7. prepare a local draft PR publication artifact without pushing or opening a
   network PR.

In short: task approval follows deterministic intake validation; read-only
research precedes read-only planning. Operators approve the plan before implementation,
and explicit review approval remains separate from the reviewer agent's report.

`loopforge run --no-input` without a new source only reports the active run. It never approves a
gate, executes an adapter, or prepares publication.

Research, plan, and review stages are adapter-fed and checked as read-only
against the project worktree. Verification produces local evidence for review;
it is not review approval and does not authorize publication. Publication is
limited to a deterministic local draft artifact under the run directory.
LoopForge does not push branches, open PRs, or publish to the network from this
workflow.

Codex stages require a Git worktree. For a temporary non-Git project,
LoopForge blocks before launching Codex and directs the operator to run
`git init`; it never initializes Git automatically or passes Codex's
repository-check bypass.

## Packs

A pack is a complete workflow capability, not only a detection rule. Its
contract can contribute:

- reusable skills under `skills/<skill>/SKILL.md`;
- named agents and their prompt files;
- permission sets for read-only, workspace-write, and deterministic work;
- an ordered workflow with agent, deterministic, and human-gated stages;
- checks, protected paths, and memory rules.

The bundled language packs inherit the `generic-code` workflow and add their
domain skills and checks. A project-local `.loopforge/packs/<name>/` contract
can override a bundled pack. Use `loopforge pack list` to compare effective
skill, agent, and stage counts, then `loopforge pack detect` to inspect the
selected pack before starting a run.

`loopforge` and `loopforge shell` open the full-screen interactive console in
a TTY. The TUI command palette and scriptable command session support
`/status`, `/guide`, `/actions`, `/next`, `/do`, `/context`, `/compact`,
`/adapter`, `/continue`, `/runs`, and `/resume`. The shell keeps a project
default adapter in `.loopforge/config.json` and uses it when `/continue` is run
without `--adapter`.

The full-screen navigation is the default interactive UI. `--interactive-ui`
remains a compatibility alias. Use `--plain` with CLI commands for plain text
without Rich rendering. It never selects an alternate interactive prompt;
`LOOPFORGE_ASCII=1` uses ASCII-safe glyphs in the full-screen view.

For scripts and tests, use:

```text
loopforge guide
loopforge shell --command "/adapter codex -- -m gpt-5"
loopforge shell --command "/export context"
loopforge shell --script commands.loopforge
```

The former prompt shell and numbered text menus have been removed. A fully
scriptable workflow uses the same action dispatch as the TUI:

```sh
loopforge run --task "Fix the failing test" --success-check "Tests pass"
loopforge shell --command "/do approve-task --confirm"
loopforge shell --command "/do run-research --confirm --execution-mode headless"
loopforge shell --command "/do run-plan --confirm --execution-mode headless"
# Inspect plan.md before granting implementation authority.
loopforge shell --command "/do approve-plan --confirm"
loopforge continue --adapter <adapter> --execution-mode headless --confirm
loopforge verify --confirm
loopforge shell --command "/do run-review --confirm --execution-mode headless"
# Inspect review.md before approving local draft preparation.
loopforge shell --command "/do approve-review --confirm"
loopforge shell --command "/do prepare-draft --confirm"
```

`--confirm` is explicit authorization for that action, not a bypass of engine
eligibility checks. Each command acts on the current run; inspect `status` first.

Kilo Code is available as `kilo-code`. Install its `kilo` executable first,
then select it with `loopforge shell --command "/adapter kilo-code"`. LoopForge
uses Kilo's read-only `ask` agent for headless research, planning, and review,
and its `code` agent for implementation. Interactive stages use a writable
harness because the final structured artifact must be saved to LoopForge's
controlled candidate path; LoopForge still rejects every other worktree change.

All agentic stages use `--execution-mode auto` by default. On Windows, Codex,
Claude Code, Kilo Code, and OpenCode open in a separate interactive terminal
rooted in the run worktree for research, planning, implementation, and review.
For research, planning, and review, the initial prompt tells the harness to save
its final Markdown to a temporary candidate file. LoopForge removes that file,
validates the artifact and the unchanged worktree, then resumes the normal
pipeline. Use `/do run-research --confirm --execution-mode headless` (or
`run-plan` / `run-review`) through `shell --command` for the read-only stages
and `loopforge continue --execution-mode headless --adapter <adapter>` for
implementation, or use `--execution-mode terminal` to require a visible launcher
instead of allowing the automatic headless fallback.

## CLI Conventions

LoopForge keeps human output readable while exposing stable formats for scripts:

- Use `--format json` or `--json` when a command is consumed by automation.
- Use `--format csv` on list commands such as `loopforge runs` and
  `loopforge pack list`.
- Use `--no-input --plain --quiet` in CI when prompts, ANSI color, and
  secondary guidance are undesirable.
- Results go to stdout. Errors, warnings, progress, and adapter stderr summaries
  go to stderr.
- `NO_COLOR`, `LOOPFORGE_NO_COLOR`, `TERM=dumb`, and `FORCE_COLOR` are honored.
- `LOOPFORGE_DEBUG=1`, `DEBUG=loopforge*`, or `--debug` enables extra failure
  diagnostics and writes a local debug log.

Runtime data is kept outside the repository by default. `LOOPFORGE_HOME` wins
when set. Existing `~/LoopForge` installs continue to use that path; otherwise
new installs use the platform data directory such as `$XDG_DATA_HOME/loopforge`
on Linux, `~/Library/Application Support/loopforge` on macOS, or
`%LOCALAPPDATA%\loopforge` on Windows.

## Package Layout and Compatibility

The product implementation lives under `src/loopforge/`:

- `cli/`: public CLI facade, parser, handlers, shared command session, and Textual terminal UI;
- `engine/`: engine facade plus storage, packs, and metrics services;
- `checks/`, `adapters/`, `contracts/`, and `templates/`: deterministic runtime
  components and their packaged data.

The corresponding `.agent/checks/` and `.agent/adapters/` scripts remain as
thin compatibility launchers. Obsolete bootstrap scripts and duplicate
policies, schemas, prompts, and templates have been removed.

Documentation lives in `docs/`, executable tests in `tests/`, and developer
utilities in `tools/`. See [repository layout](docs/repository-layout.md) for
the role of each directory, including local hidden directories.

## Run-screen UX direction (planned)

The [run TUI UX plan](docs/plans/2026-10-20-001-run-live-context-ux-plan.md)
defines four complementary views: **Live** (focused execution events),
**Context** (per-attempt exact prompt and its source sections), **Changes**
(verified workspace diffs), and **Evidences** (artifacts and validation records).
This is a **proposal, not shipped behavior**. The current run screen still shows
System Prompt / Agent Output / Implementation Contract together; Changes and
Evidences are placeholders. Native agent observation behavior is documented in
[agent-run-observation](docs/decisions/agent-run-observation.md).

## Product Principle

LoopForge should be more autonomous than the original pilot, but not opaque.
Every run should show:

- what goal is being pursued;
- which loop is active;
- what evidence proves progress;
- when the agent is stuck;
- what memory will be retained;
- what action, if any, needs a human decision.

Verification is evidence, not authority. Review approval is separate from
deterministic checks, and draft publication is only a local artifact until a
human chooses an external publishing path.
