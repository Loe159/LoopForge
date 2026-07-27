"""Typed model for a parsed stage artifact (frontmatter + body)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StageArtifact:
    """Wraps parse_frontmatter output: name, frontmatter, body, optional path."""

    name: str
    frontmatter: dict[str, str]
    body: str
    path: str | None = None

    _KNOWN_KEYS = frozenset({"name", "frontmatter", "body", "path"})

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "frontmatter": dict(self.frontmatter),
            "body": self.body,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> StageArtifact:
        unknown = set(data) - cls._KNOWN_KEYS
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            name=data["name"],
            frontmatter=dict(data.get("frontmatter", {})),
            body=data["body"],
            path=data.get("path"),
        )
