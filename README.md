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

`loopforge run` is the cockpit for the active run. With a new task or approved
GitHub issue, it creates a run. With an active run and no new source, it resumes
that run and offers the next eligible stage one step at a time:

1. task approval (`agent:approved` for GitHub issues, local confirmation for
   manual tasks);
2. run read-only research and write `research.md`;
3. run read-only planning and write `plan.md`;
4. approve the plan before implementation;
5. execute implementation with `loopforge continue`;
6. run deterministic verification with `loopforge verify`;
7. explicit review approval;
8. prepare a local draft PR publication artifact without pushing or opening a
   network PR.

`loopforge run --no-input` only reports the cockpit state. It never approves a
gate, executes an adapter, or prepares publication.

Research and plan stages are adapter-fed and checked as read-only against the
project worktree. Verification produces local evidence for review; it is not
review approval and does not authorize publication. Publication is limited to a
deterministic local draft artifact under the run directory. LoopForge does not
push branches, open PRs, or publish to the network from this workflow.

`loopforge shell` starts an interactive prompt with slash commands such as
`/status`, `/guide`, `/actions`, `/next`, `/do`, `/context`, `/compact`,
`/adapter`, `/continue`, `/runs`, and `/resume`. The shell keeps a project
default adapter in `.loopforge/config.json` and uses it when `/continue` is run
without `--adapter`.

For scripts and tests, use:

```text
loopforge guide
loopforge shell --command "/adapter codex -- -m gpt-5"
loopforge shell --command "/export context"
loopforge shell --script commands.loopforge
```

## CLI Conventions

LoopForge keeps human output readable while exposing stable formats for scripts:

- Use `--format json` or `--json` when a command is consumed by automation.
- Use `--format csv` on list commands such as `loopforge runs` and
  `loopforge pack list`.
- Use `--no-input --no-color --quiet` in CI when prompts, ANSI color, and
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

## Imported Core

The initial import lives under `.agent/` to keep the proven scripts runnable
while the public CLI is designed. Important imported pieces:

- `.agent/checks/diff_policy.py`
- `.agent/checks/generate_complete_patch.py`
- `.agent/checks/classify_patch_risk.py`
- `.agent/checks/validate_artifacts.py`
- `.agent/checks/isolated_process.py`
- `.agent/checks/record_run_metrics.py`
- `.agent/adapters/local_implementation_adapter.py`
- `.agent/templates/`
- `.agent/prompts/`

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
