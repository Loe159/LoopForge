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

`loopforge run --no-input` only reports the cockpit state. It never approves a
gate, executes an adapter, or prepares publication.

Research, plan, and review stages are adapter-fed and checked as read-only
against the project worktree. Verification produces local evidence for review;
it is not review approval and does not authorize publication. Publication is
limited to a deterministic local draft artifact under the run directory.
LoopForge does not push branches, open PRs, or publish to the network from this
workflow.

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

## Package Layout and Compatibility

The product implementation lives under `src/loopforge/`:

- `cli/`: public CLI facade, parser, handlers, interactive shell, and terminal UI;
- `engine/`: engine facade plus storage, packs, and metrics services;
- `checks/`, `adapters/`, `contracts/`, and `templates/`: deterministic runtime
  components and their packaged data.

The corresponding `.agent/checks/` and `.agent/adapters/` scripts remain as
thin compatibility launchers. Other inherited `.agent/` content remains
bootstrap material until it has a product-owned replacement.

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
