"""Read-only, native agent TODO projections for the selected run session."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Any


@dataclass(frozen=True)
class AgentTodo:
    text: str
    status: str


@dataclass(frozen=True)
class AgentPlan:
    items: tuple[AgentTodo, ...] = ()

    @property
    def completed(self) -> int:
        return sum(item.status == "completed" for item in self.items)

    @property
    def count(self) -> int:
        return len(self.items)


def project_agent_plan(events: tuple[Mapping[str, Any], ...]) -> AgentPlan:
    """Use only native, structured TODO items, never transcript prose.

    Each retained complete native plan snapshot replaces earlier snapshots.
    This projection must receive observations from the *selected* session.
    """
    latest = AgentPlan()
    for event in events:
        if event.get("kind") != "plan" or not isinstance(event.get("plan_items"), list):
            continue
        items: list[AgentTodo] = []
        for value in event["plan_items"][:60]:
            if not isinstance(value, Mapping):
                continue
            name = value.get("text")
            status = value.get("status")
            if not isinstance(name, str) or not name.strip() or not isinstance(status, str):
                continue
            if status not in {"completed", "in_progress", "pending", "failed", "unknown"}:
                status = "unknown"
            items.append(AgentTodo(name.strip()[:140], status))
        latest = AgentPlan(tuple(items))
    return latest
