# LoopForge pack contract

A pack is an effective set of skills, agents, permission boundaries, workflow
stages, checks, protected paths, and memory rules. Domain packs normally inherit
the `generic-code` base with `"extends": "generic-code"`.

```text
<pack>/
  pack.json
  SKILL.md
  skills/<skill>/SKILL.md
  agents.json
  agents/<agent>.md
  permissions.json
  workflow.json
  checks.json
  protected-paths.json
  memory-rules.md
```

Only `pack.json` is mandatory for legacy and minimal packs. Once a contribution
file or skills directory is declared, `PackRegistry` validates that it exists
and that agent, permission-set, prompt, skill, and workflow-stage references are
consistent. The resolved contract is stored in `run.json`, so a run remains
auditable even when the source pack later changes.

Project-local packs under `.loopforge/packs/<name>/` take precedence over the
bundled pack with the same name.
