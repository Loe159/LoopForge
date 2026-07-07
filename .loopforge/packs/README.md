# Project Packs

Project packs adapt LoopForge to a repository or domain without changing the
engine.

A pack should define:

- project detection rules;
- trusted setup commands;
- verification commands;
- protected paths;
- task-specific skills;
- memory promotion rules.

Verification commands can be configured without editing engine code by adding
`checks.json` under `.loopforge/packs/<pack-name>/`.

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

Examples planned:

- `generic-code`
- `python`
- `node`
- `intellij-plugin`
- `documentation`
- `email-triage`
