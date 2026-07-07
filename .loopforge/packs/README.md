# Project Packs

Project packs adapt LoopForge to a repository or domain without changing the
engine.

A pack defines:

- `pack.json`: name, description, detection rules, contributed skills, and
  contribution file names;
- `SKILL.md`: operator-facing guidance loaded as a pack skill;
- `checks.json`: deterministic verification commands;
- `protected-paths.json`: pack-specific path patterns that raise supervision
  risk;
- `memory-rules.md`: human-readable memory promotion guidance.

Verification commands can be configured without editing engine code by adding or
overriding `checks.json` under `.loopforge/packs/<pack-name>/`.

```json
{
  "version": 1,
  "checks": [
    {
      "name": "git-diff-check",
      "command": ["git", "diff", "--check"],
      "timeout_seconds": 60
    }
  ]
}
```

Commands are executed without a shell from the target repository. Command and
environment string values can use `{python}`, `{repo}`, `{run_dir}`, and
`{patch}` placeholders.

Initial packs:

- `generic-code`
- `python`
- `node`
- `documentation`
- `intellij-plugin`

Project-local packs override bundled packs with the same name.
