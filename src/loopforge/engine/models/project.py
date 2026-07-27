"""Typed model for a project's config.json structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loopforge.engine.models.schema import CURRENT_CONFIG_SCHEMA


@dataclass(frozen=True)
class ProjectConfig:
    """Frozen representation of the on-disk project ``config.json``."""

    schema_version: int = int(CURRENT_CONFIG_SCHEMA)
    project_id: str = ""
    project_name: str = ""
    profile: str = ""
    run_root: str = ""
    current_run_id: str | None = None
    default_adapter: str = ""
    default_adapter_args: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    _KNOWN_KEYS = frozenset(
        {
            "schema_version",
            "project_id",
            "project_name",
            "profile",
            "run_root",
            "current_run_id",
            "default_adapter",
            "default_adapter_args",
            "created_at",
            "updated_at",
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "profile": self.profile,
            "run_root": self.run_root,
            "current_run_id": self.current_run_id,
            "default_adapter": self.default_adapter,
            "default_adapter_args": self.default_adapter_args,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectConfig:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            schema_version=data.get("schema_version", int(CURRENT_CONFIG_SCHEMA)),
            project_id=data.get("project_id", ""),
            project_name=data.get("project_name", ""),
            profile=data.get("profile", ""),
            run_root=data.get("run_root", ""),
            current_run_id=data.get("current_run_id"),
            default_adapter=data.get("default_adapter", ""),
            default_adapter_args=list(data.get("default_adapter_args", [])),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
