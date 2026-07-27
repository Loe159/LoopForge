"""Typed model for a run's run.json top-level structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunState:
    """Frozen representation of the top-level fields of a run."""

    schema_version: int
    run_id: str
    task_id: str
    task: str
    project_root: str
    status: str
    profile: str
    pack: str
    created_at: str
    workspace: dict[str, Any]
    pack_contract: dict[str, Any]
    current_stage: str
    stage_statuses: dict[str, Any]
    success_checks: list[str]
    acceptance_criteria: list[str]
    verification_commands: list[dict[str, Any]]
    limits: dict[str, Any]
    attempt_count: int
    attempts: list[dict[str, Any]]
    blockers: list[str]
    artifacts: dict[str, str]
    memory: dict[str, Any]
    base_commit: str | None = None
    loop_contract: dict[str, Any] | None = None
    task_validation: dict[str, Any] | None = None
    human_gates: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    publish_eligibility: dict[str, Any] | None = None
    updated_at: str | None = None
    archived: bool = False
    archived_at: str | None = None
    evidence: dict[str, Any] | None = None

    _KNOWN_KEYS = frozenset(
        {
            "schema_version",
            "run_id",
            "task_id",
            "task",
            "project_root",
            "status",
            "profile",
            "pack",
            "created_at",
            "workspace",
            "pack_contract",
            "current_stage",
            "stage_statuses",
            "success_checks",
            "acceptance_criteria",
            "verification_commands",
            "limits",
            "attempt_count",
            "attempts",
            "blockers",
            "artifacts",
            "memory",
            "base_commit",
            "loop_contract",
            "task_validation",
            "human_gates",
            "approval",
            "risk",
            "publish_eligibility",
            "updated_at",
            "archived",
            "archived_at",
            "evidence",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task": self.task,
            "project_root": self.project_root,
            "status": self.status,
            "profile": self.profile,
            "pack": self.pack,
            "created_at": self.created_at,
            "workspace": self.workspace,
            "pack_contract": self.pack_contract,
            "current_stage": self.current_stage,
            "stage_statuses": self.stage_statuses,
            "success_checks": self.success_checks,
            "acceptance_criteria": self.acceptance_criteria,
            "verification_commands": self.verification_commands,
            "limits": self.limits,
            "attempt_count": self.attempt_count,
            "attempts": self.attempts,
            "blockers": self.blockers,
            "artifacts": self.artifacts,
            "memory": self.memory,
            "base_commit": self.base_commit,
            "loop_contract": self.loop_contract,
            "task_validation": self.task_validation,
            "human_gates": self.human_gates,
            "approval": self.approval,
            "risk": self.risk,
            "publish_eligibility": self.publish_eligibility,
            "updated_at": self.updated_at,
            "archived": self.archived,
            "archived_at": self.archived_at,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RunState:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            schema_version=data["schema_version"],
            run_id=data["run_id"],
            task_id=data["task_id"],
            task=data["task"],
            project_root=data["project_root"],
            status=data["status"],
            profile=data["profile"],
            pack=data["pack"],
            created_at=data["created_at"],
            workspace=dict(data.get("workspace", {})),
            pack_contract=dict(data.get("pack_contract", {})),
            current_stage=data["current_stage"],
            stage_statuses=dict(data.get("stage_statuses", {})),
            success_checks=list(data.get("success_checks", [])),
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
            verification_commands=list(data.get("verification_commands", [])),
            limits=dict(data.get("limits", {})),
            attempt_count=data["attempt_count"],
            attempts=list(data.get("attempts", [])),
            blockers=list(data.get("blockers", [])),
            artifacts=dict(data.get("artifacts", {})),
            memory=dict(data.get("memory", {})),
            base_commit=data.get("base_commit"),
            loop_contract=data.get("loop_contract"),
            task_validation=data.get("task_validation"),
            human_gates=data.get("human_gates"),
            approval=data.get("approval"),
            risk=data.get("risk"),
            publish_eligibility=data.get("publish_eligibility"),
            updated_at=data.get("updated_at"),
            archived=data.get("archived", False),
            archived_at=data.get("archived_at"),
            evidence=data.get("evidence"),
        )
