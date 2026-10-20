"""Open a synthetic Run / Live showcasing Agent Message Markdown rendering.

From the repository root:
    PYTHONPATH=src .venv/bin/python tools/demo_agent_message.py

All run events are in memory; no adapter or filesystem changes.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from loopforge.cli.textual_app import LoopForgeApp

if __package__:
    from .demo_tool_call import demonstration_snapshot
else:
    from demo_tool_call import demonstration_snapshot


AGENT_MARKDOWN = """J'ai analysé la configuration du projet.

## Résultats de l'analyse

Le fichier `pyproject.toml` contient **3 dépendances** à vérifier.

- **pytest** — configuration correcte
- **ruff** — version obsolète
- **mypy** — aucune configuration

Pour vérifier les versions :

```python
import importlib.metadata

for name in ["pytest", "ruff"]:
    print(importlib.metadata.version(name))
```

> La version de Ruff devrait être actualisée avant validation.

Documentation : [guide officiel](https://example.org/guide).
"""


class AgentMessageDemo(LoopForgeApp):
    def __init__(self):
        super().__init__(SimpleNamespace(project_dir=Path.cwd(), theme="dark"),
                         load_on_mount=False)

    def _suspend_run_follow(self):
        # The fixture is not backed by a persisted run; do not flush StateStore.
        self._run_follow_tail = False

    def _snapshot_with_messages(self, *, final: bool):
        source = demonstration_snapshot(self, final=final)
        examples = [
            {"kind": "message", "title": "Agent", "native_id": "agent-1",
             "body": AGENT_MARKDOWN, "order": 0},
            {"kind": "tool", "title": "Shell", "call_id": "test-1",
             "status": "completed", "category": "command",
             "body": "  $ python -m pytest\n  Output\n    12 tests passed", "order": 1},
            {"kind": "message", "title": "Agent", "native_id": "agent-2",
             "body": "### Conclusion\n\n**Vérification terminée.**"
                     if final else "### Concl",
             "order": 2},
        ]
        return replace(
            source,
            run=replace(
                source.run,
                agent=replace(source.run.agent, structured_events=tuple(examples),
                              event_count=len(examples)),
            ),
        )

    def on_mount(self):
        # Call the base App mounting logic but not the ToolCallDemo's timer.
        from loopforge.cli.textual_app.app import _snapshot_run_identity
        super().on_mount()
        self._screen = "run"
        snapshot = self._snapshot_with_messages(final=False)
        self._operation_run_identity = _snapshot_run_identity(snapshot)
        self._render_snapshot(snapshot)
        self.set_timer(5.0, self.finish_demo)

    def finish_demo(self):
        self._render_snapshot(self._snapshot_with_messages(final=True))


if __name__ == "__main__":
    AgentMessageDemo().run()
