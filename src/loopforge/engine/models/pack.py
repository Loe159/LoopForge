"""Frozen, complete pack contract model stored on every run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EffectivePackContract:
    """Frozen, complete pack contract stored on every run."""

    name: str
    version: int
    description: str = ""

    checks: list[dict] = field(default_factory=list)
    checks_content_hash: str = ""
    checks_source: str | None = None
    checks_origin: str | None = None
    protected_paths: list[dict] = field(default_factory=list)
    protected_paths_content_hash: str = ""
    memory_rules: str = ""
    memory_rules_hash: str = ""
    permissions: dict[str, Any] = field(default_factory=dict)
    agents: list[dict] = field(default_factory=list)
    workflow: list[dict] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)

    detection: str = ""
    detection_score: int = 0

    contract_hash: str = ""
    skills_content_hash: str = ""
    frozen_at: str = ""

    source: str | None = None
    inherited_from: list[str] = field(default_factory=list)

    _KNOWN_KEYS = frozenset(
        {
            "name",
            "version",
            "description",
            "checks",
            "checks_content_hash",
            "checks_source",
            "checks_origin",
            "protected_paths",
            "protected_paths_content_hash",
            "memory_rules",
            "memory_rules_hash",
            "permissions",
            "agents",
            "workflow",
            "skills",
            "detection",
            "detection_score",
            "contract_hash",
            "skills_content_hash",
            "frozen_at",
            "source",
            "inherited_from",
            # Legacy alias written by to_dict and present in persisted data.
            # Tolerated during strict validation, but never read by from_dict.
            "permission_sets",
        }
    )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "checks": self.checks,
            "checks_content_hash": self.checks_content_hash,
            "checks_source": self.checks_source,
            "checks_origin": self.checks_origin,
            "protected_paths": self.protected_paths,
            "protected_paths_content_hash": self.protected_paths_content_hash,
            "memory_rules": self.memory_rules,
            "memory_rules_hash": self.memory_rules_hash,
            "permissions": self.permissions,
            "permission_sets": self.permissions,
            "agents": self.agents,
            "workflow": self.workflow,
            "skills": self.skills,
            "detection": self.detection,
            "detection_score": self.detection_score,
            "contract_hash": self.contract_hash,
            "skills_content_hash": self.skills_content_hash,
            "frozen_at": self.frozen_at,
            "source": self.source,
            "inherited_from": self.inherited_from,
        }

    @classmethod
    def from_dict(cls, data: dict) -> EffectivePackContract:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            name=data.get("name", ""),
            version=data.get("version", 1),
            description=data.get("description", ""),
            checks=data.get("checks", []),
            checks_content_hash=data.get("checks_content_hash", ""),
            checks_source=data.get("checks_source"),
            checks_origin=data.get("checks_origin"),
            protected_paths=data.get("protected_paths", []),
            protected_paths_content_hash=data.get("protected_paths_content_hash", ""),
            memory_rules=data.get("memory_rules", ""),
            memory_rules_hash=data.get("memory_rules_hash", ""),
            permissions=data.get("permissions", {}),
            agents=data.get("agents", []),
            workflow=data.get("workflow", []),
            skills=data.get("skills", []),
            detection=data.get("detection", ""),
            detection_score=data.get("detection_score", 0),
            contract_hash=data.get("contract_hash", ""),
            skills_content_hash=data.get("skills_content_hash", ""),
            frozen_at=data.get("frozen_at", ""),
            source=data.get("source"),
            inherited_from=data.get("inherited_from", []),
        )
