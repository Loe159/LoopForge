"""Action scope model: the validated target of an app command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ActionScope:
    """The validated project/run target an app command operates on."""

    project_id: str
    project_path: Path
    run_id: str | None
    revision: int | None = None
    snapshot: str | None = None

    def validate(self) -> None:
        from loopforge.engine.path_resolvers import validate_identifier as _validate

        _validate(self.project_id, "project")
        if self.run_id is not None:
            _validate(self.run_id, "run")
        if not self.project_path.is_dir():
            raise ValueError(f"Project path does not exist: {self.project_path}")

    def revalidate(self, store: Any) -> ActionScope | None:
        from loopforge.engine import _load_config_scope

        reloaded = _load_config_scope(self.project_path)
        if reloaded is None:
            return ActionScope(
                project_id=self.project_id,
                project_path=self.project_path,
                run_id=self.run_id,
                revision=(self.revision or 0) + 1,
                snapshot="config_missing",
            )
        if reloaded.project_id != self.project_id:
            return ActionScope(
                project_id=reloaded.project_id,
                project_path=reloaded.project_path,
                run_id=reloaded.run_id,
                revision=(self.revision or 0) + 1,
                snapshot="project_changed",
            )
        if reloaded.run_id != self.run_id:
            return ActionScope(
                project_id=reloaded.project_id,
                project_path=reloaded.project_path,
                run_id=reloaded.run_id,
                revision=(self.revision or 0) + 1,
                snapshot="run_changed",
            )
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_path": str(self.project_path),
            "run_id": self.run_id,
            "revision": self.revision,
            "snapshot": self.snapshot,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ActionScope:
        known = {"project_id", "project_path", "run_id", "revision", "snapshot"}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown keys in {cls.__name__}: {sorted(unknown)}")
        return cls(
            project_id=data["project_id"],
            project_path=Path(data["project_path"]),
            run_id=data.get("run_id"),
            revision=data.get("revision"),
            snapshot=data.get("snapshot"),
        )
