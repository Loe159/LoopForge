"""Unified diagnostic and repair service for LoopForge."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine.recovery import safe_read_json
from loopforge.engine.projects import registered_projects, load_registry
from loopforge.engine.indexes import (
    read_run_index,
    rebuild_run_index,
    run_index_path,
    dirty_marker_path,
)
from loopforge.engine.models.schema import (
    CURRENT_RUN_SCHEMA,
    CURRENT_CONFIG_SCHEMA,
    CURRENT_REGISTRY_SCHEMA,
    CURRENT_INDEX_SCHEMA,
)

logger = logging.getLogger(__name__)


@dataclass
class DoctorDiagnostic:
    level: str
    category: str
    source: str
    message: str
    proposed_action: str
    repairable: bool
    repair_description: str = ""


@dataclass
class DoctorResult:
    ok: bool
    diagnostics: list[DoctorDiagnostic]
    summary: str
    repairs_available: int
    examined_at: str


class DoctorService:

    def __init__(self, home: Path | None = None, project_dir: Path | None = None):
        from loopforge.engine import loopforge_home as _loopforge_home

        self._home = _loopforge_home(home=home)
        self._project_dir = Path(project_dir) if project_dir else None
        self._store = DEFAULT_JSON_STORE

    def examine(self) -> DoctorResult:
        diagnostics: list[DoctorDiagnostic] = []

        diagnostics.extend(self._check_corrupt_files())
        diagnostics.extend(self._check_stale_indexes())
        diagnostics.extend(self._check_orphan_worktrees())
        diagnostics.extend(self._check_invalid_roots())
        diagnostics.extend(self._check_pack_issues())
        diagnostics.extend(self._check_schema_compatibility())
        diagnostics.extend(self._check_current_run_id())

        errors = [d for d in diagnostics if d.level == "error"]
        repairable = sum(1 for d in diagnostics if d.repairable)

        return DoctorResult(
            ok=len(errors) == 0,
            diagnostics=diagnostics,
            summary=f"Found {len(errors)} error(s), {len(diagnostics)} issue(s) total",
            repairs_available=repairable,
            examined_at=datetime.now(timezone.utc).isoformat(),
        )

    def repair(self, diagnostic: DoctorDiagnostic) -> tuple[bool, str]:
        category = diagnostic.category
        if category == "stale_index" and diagnostic.repairable:
            return self._repair_stale_index(diagnostic.source)
        if category == "invalid_root" and diagnostic.repairable:
            return self._repair_invalid_root(diagnostic.source)
        if category == "schema_compatibility" and diagnostic.repairable:
            return self._repair_schema_migration(diagnostic.source)
        if category == "current_run_id" and diagnostic.repairable:
            return self._repair_current_run_id(diagnostic.source)
        if category == "orphan_worktree" and diagnostic.repairable:
            return self._repair_orphan_worktree(diagnostic.source)
        return False, f"No repair available for category '{category}'"

    def repair_all(self) -> tuple[int, list[str]]:
        result = self.examine()
        repaired = 0
        messages: list[str] = []
        for diag in result.diagnostics:
            if diag.repairable:
                ok, msg = self.repair(diag)
                if ok:
                    repaired += 1
                messages.append(f"[{diag.category}] {msg}")
        return repaired, messages

    def _check_corrupt_files(self) -> list[DoctorDiagnostic]:
        diagnostics: list[DoctorDiagnostic] = []
        for path in self._all_json_paths():
            data, diagnostic = safe_read_json(self._store, path)
            if data is None and diagnostic and "File not found" not in (diagnostic or ""):
                diagnostics.append(DoctorDiagnostic(
                    level="error",
                    category="corruption",
                    source=str(path),
                    message=f"Corrupt file: {diagnostic}",
                    proposed_action="File quarantined. Restore from backup or regenerate.",
                    repairable=False,
                ))
        return diagnostics

    def _check_stale_indexes(self) -> list[DoctorDiagnostic]:
        diagnostics: list[DoctorDiagnostic] = []

        projects_dir = self._home / "projects"
        if not projects_dir.is_dir():
            return diagnostics

        for project_entry in projects_dir.iterdir():
            if not project_entry.is_dir():
                continue
            run_root = project_entry / "runs"
            if not run_root.is_dir():
                continue

            index_path = run_index_path(run_root)
            if not index_path.exists():
                run_dirs = [p for p in run_root.iterdir() if p.is_dir()]
                if run_dirs:
                    diagnostics.append(DoctorDiagnostic(
                        level="warning",
                        category="stale_index",
                        source=str(run_root),
                        message=f"Missing run index for {project_entry.name} ({len(run_dirs)} run(s) on disk)",
                        proposed_action="Rebuild index from run.json files on disk.",
                        repairable=True,
                        repair_description="Rebuild run index by scanning run directories.",
                    ))
                continue

            if dirty_marker_path(run_root).exists():
                diagnostics.append(DoctorDiagnostic(
                    level="warning",
                    category="stale_index",
                    source=str(run_root),
                    message=f"Dirty index marker for {project_entry.name}",
                    proposed_action="Clear dirty marker and rebuild index.",
                    repairable=True,
                    repair_description="Clear dirty marker and rebuild run index.",
                ))
                continue

            index = read_run_index(self._store, run_root)
            if index is None:
                run_dirs = [p for p in run_root.iterdir() if p.is_dir()]
                if run_dirs:
                    diagnostics.append(DoctorDiagnostic(
                        level="warning",
                        category="stale_index",
                        source=str(run_root),
                        message=f"Unreadable or corrupt index for {project_entry.name} ({len(run_dirs)} run(s) on disk)",
                        proposed_action="Rebuild index from run.json files on disk.",
                        repairable=True,
                        repair_description="Rebuild run index by scanning run directories.",
                    ))
                continue

            indexed_runs = {str(r.get("run_id") or "") for r in index.get("runs", []) if isinstance(r, dict)}
            disk_runs = set()
            for run_entry in run_root.iterdir():
                if run_entry.is_dir() and (run_entry / "run.json").is_file():
                    disk_runs.add(run_entry.name)

            if indexed_runs != disk_runs:
                missing_from_index = disk_runs - indexed_runs
                extra_in_index = indexed_runs - disk_runs
                detail_parts = []
                if missing_from_index:
                    detail_parts.append(f"{len(missing_from_index)} run(s) on disk but not in index")
                if extra_in_index:
                    detail_parts.append(f"{len(extra_in_index)} run(s) in index but not on disk")
                diagnostics.append(DoctorDiagnostic(
                    level="warning" if missing_from_index else "info",
                    category="stale_index",
                    source=str(run_root),
                    message=f"Stale index for {project_entry.name}: {', '.join(detail_parts)}",
                    proposed_action="Rebuild index from run.json files on disk.",
                    repairable=True,
                    repair_description="Rebuild run index by scanning run directories.",
                ))

        return diagnostics

    def _check_orphan_worktrees(self) -> list[DoctorDiagnostic]:
        diagnostics: list[DoctorDiagnostic] = []

        projects_dir = self._home / "projects"
        if not projects_dir.is_dir():
            return diagnostics

        for project_entry in projects_dir.iterdir():
            if not project_entry.is_dir():
                continue
            workspaces_dir = project_entry / "workspaces"
            if not workspaces_dir.is_dir():
                continue

            run_root = project_entry / "runs"
            valid_run_ids: set[str] = set()
            if run_root.is_dir():
                for run_entry in run_root.iterdir():
                    if run_entry.is_dir() and (run_entry / "run.json").is_file():
                        valid_run_ids.add(run_entry.name)

            for ws_entry in workspaces_dir.iterdir():
                if not ws_entry.is_dir():
                    continue
                ws_name = ws_entry.name
                if ws_name not in valid_run_ids:
                    diagnostics.append(DoctorDiagnostic(
                        level="warning",
                        category="orphan_worktree",
                        source=str(ws_entry),
                        message=f"Orphan workspace for project {project_entry.name}, run '{ws_name}'",
                        proposed_action="Remove orphan workspace directory.",
                        repairable=True,
                        repair_description="Remove orphan workspace directory to reclaim disk space.",
                    ))

        return diagnostics

    def _check_invalid_roots(self) -> list[DoctorDiagnostic]:
        diagnostics: list[DoctorDiagnostic] = []

        try:
            projects = registered_projects(self._home)
        except Exception:
            return diagnostics

        for record in projects:
            path_str = record.get("path", "")
            if not path_str:
                continue
            project_path = Path(path_str).expanduser()
            if not project_path.exists():
                diagnostics.append(DoctorDiagnostic(
                    level="warning",
                    category="invalid_root",
                    source=str(path_str),
                    message=f"Registered project '{record.get('name', record.get('project_id', ''))}' path does not exist: {project_path}",
                    proposed_action="Remove stale registration. Use 'loopforge projects' to review.",
                    repairable=True,
                    repair_description="Remove stale project registration from registry.",
                ))
                continue
            if not project_path.is_dir():
                diagnostics.append(DoctorDiagnostic(
                    level="warning",
                    category="invalid_root",
                    source=str(path_str),
                    message=f"Registered project '{record.get('name', record.get('project_id', ''))}' path is not a directory: {project_path}",
                    proposed_action="Remove stale registration. Use 'loopforge projects' to review.",
                    repairable=True,
                    repair_description="Remove stale project registration from registry.",
                ))

        if self._project_dir is not None:
            try:
                self._project_dir.resolve().relative_to(self._home.resolve())
            except ValueError:
                diagnostics.append(DoctorDiagnostic(
                    level="warning",
                    category="invalid_root",
                    source=str(self._project_dir),
                    message=f"Current project directory is outside LOOPFORGE_HOME ({self._home})",
                    proposed_action="Use 'loopforge doctor' to migrate legacy external run roots or reinitialize.",
                    repairable=False,
                ))

        return diagnostics

    def _check_pack_issues(self) -> list[DoctorDiagnostic]:
        diagnostics: list[DoctorDiagnostic] = []

        if self._project_dir is None:
            return diagnostics

        try:
            from loopforge.engine.packs import diagnose_pack_issues as _diagnose_pack_issues
            pack_issues = _diagnose_pack_issues(self._project_dir)
        except Exception:
            return diagnostics

        for issue in pack_issues:
            level = str(issue.get("level", "warning"))
            diagnostics.append(DoctorDiagnostic(
                level=level,
                category="ignored_pack",
                source=str(self._project_dir / ".loopforge" / "packs" / str(issue.get("pack_name", ""))),
                message=f"Pack '{issue.get('pack_name', 'unknown')}': {issue.get('issue', '')}",
                proposed_action=str(issue.get("action", "Resolve the issue manually.")),
                repairable=False,
            ))

        return diagnostics

    def _check_schema_compatibility(self) -> list[DoctorDiagnostic]:
        diagnostics: list[DoctorDiagnostic] = []

        current_schemas = {
            "run.json": int(CURRENT_RUN_SCHEMA),
            "config.json": int(CURRENT_CONFIG_SCHEMA),
            "registry.json": int(CURRENT_REGISTRY_SCHEMA),
            "index.json": int(CURRENT_INDEX_SCHEMA),
        }

        for path in self._all_json_paths():
            file_name = path.name
            expected_schema = current_schemas.get(file_name)
            if expected_schema is None:
                continue

            data, diagnostic = safe_read_json(self._store, path)
            if data is None:
                continue

            actual_schema = data.get("schema_version")
            if actual_schema is None:
                continue

            try:
                actual_schema = int(actual_schema)
            except (TypeError, ValueError):
                continue

            if actual_schema < expected_schema:
                diagnostics.append(DoctorDiagnostic(
                    level="warning",
                    category="schema_compatibility",
                    source=str(path),
                    message=f"{file_name} schema is v{actual_schema}, current is v{expected_schema}",
                    proposed_action=f"Migrate {file_name} to schema v{expected_schema}.",
                    repairable=True,
                    repair_description=f"Run migration on {file_name} to update schema version.",
                ))

        return diagnostics

    def _check_current_run_id(self) -> list[DoctorDiagnostic]:
        diagnostics: list[DoctorDiagnostic] = []

        projects_dir = self._home / "projects"
        if not projects_dir.is_dir():
            return diagnostics

        try:
            registry_records = registered_projects(self._home)
            project_id_to_path: dict[str, Path] = {}
            for record in registry_records:
                pid = str(record.get("project_id") or "")
                path_str = str(record.get("path") or "")
                if pid and path_str:
                    project_id_to_path[pid] = Path(path_str).expanduser()
        except Exception:
            project_id_to_path = {}

        for project_entry in projects_dir.iterdir():
            if not project_entry.is_dir():
                continue
            run_root = project_entry / "runs"
            if not run_root.is_dir():
                continue

            project_id = project_entry.name
            target_dir = project_id_to_path.get(project_id)
            if target_dir is None:
                if self._project_dir is not None:
                    target_dir = self._project_dir
                else:
                    continue

            if not target_dir.is_dir():
                continue
            lf_config = target_dir / ".loopforge" / "config.json"
            if not lf_config.is_file():
                continue

            data, diagnostic = safe_read_json(self._store, lf_config)
            if data is None:
                continue

            current_run_id = data.get("current_run_id")
            if not current_run_id or not isinstance(current_run_id, str) or not current_run_id.strip():
                continue

            current_run_id = current_run_id.strip()
            run_dir = run_root / current_run_id
            if not run_dir.is_dir():
                diagnostics.append(DoctorDiagnostic(
                    level="warning",
                    category="current_run_id",
                    source=str(lf_config),
                    message=f"current_run_id '{current_run_id}' points to nonexistent run directory: {run_dir}",
                    proposed_action="Reset current_run_id to None. The next run operation will be on the most recent active run.",
                    repairable=True,
                    repair_description="Set current_run_id to None in config.json.",
                ))

        return diagnostics

    def _all_json_paths(self) -> list[Path]:
        paths: list[Path] = []

        registry_path = self._home / "projects" / "registry.json"
        if registry_path.is_file():
            paths.append(registry_path)
        trusted_path = self._home / "trusted_packs.json"
        if trusted_path.is_file():
            paths.append(trusted_path)

        projects_dir = self._home / "projects"
        if projects_dir.is_dir():
            for project_entry in projects_dir.iterdir():
                if not project_entry.is_dir():
                    continue
                run_root = project_entry / "runs"
                if run_root.is_dir():
                    index_path = run_root / "index.json"
                    if index_path.is_file():
                        paths.append(index_path)
                    dirty_path = run_root / ".index-dirty.json"
                    if dirty_path.is_file():
                        paths.append(dirty_path)
                    for run_entry in run_root.iterdir():
                        if run_entry.is_dir():
                            run_json = run_entry / "run.json"
                            if run_json.is_file():
                                paths.append(run_json)

        if self._project_dir is not None:
            lf_config = self._project_dir / ".loopforge" / "config.json"
            if lf_config.is_file():
                paths.append(lf_config)
            packs_dir = self._project_dir / ".loopforge" / "packs"
            if packs_dir.is_dir():
                for pack_entry in packs_dir.iterdir():
                    if pack_entry.is_dir():
                        pack_json = pack_entry / "pack.json"
                        if pack_json.is_file():
                            paths.append(pack_json)

        return paths

    def _repair_stale_index(self, run_root_str: str) -> tuple[bool, str]:
        from loopforge.engine import utc_now as _utc_now

        run_root = Path(run_root_str)
        if not run_root.is_dir():
            return False, f"Run root does not exist: {run_root}"

        try:
            current_run_id = None
            index = rebuild_run_index(
                self._store,
                run_root,
                current_run_id=current_run_id,
                timestamp=_utc_now(),
            )
            return True, f"Index rebuilt for {run_root}: {len(index.get('runs', []))} run(s)"
        except Exception as exc:
            return False, f"Failed to rebuild index for {run_root}: {exc}"

    def _repair_invalid_root(self, path_str: str) -> tuple[bool, str]:
        try:
            registry = load_registry(self._home)
            records = registry["projects"]
            assert isinstance(records, dict)
            to_remove = [
                pid for pid, record in records.items()
                if isinstance(record, dict) and str(record.get("path", "")) == path_str
            ]
            if not to_remove:
                return False, f"No registration found for path: {path_str}"
            for pid in to_remove:
                records.pop(pid, None)
            from loopforge.engine.projects import save_registry
            save_registry(self._home, registry)
            return True, f"Removed {len(to_remove)} stale registration(s) for path: {path_str}"
        except Exception as exc:
            return False, f"Failed to remove stale registration: {exc}"

    def _repair_schema_migration(self, path_str: str) -> tuple[bool, str]:
        path = Path(path_str)
        if not path.is_file():
            return False, f"File not found: {path}"

        data, diagnostic = safe_read_json(self._store, path)
        if data is None:
            return False, f"Cannot read file for migration: {diagnostic}"

        from loopforge.engine.models.schema import (
            CURRENT_RUN_SCHEMA,
            CURRENT_CONFIG_SCHEMA,
            CURRENT_REGISTRY_SCHEMA,
            CURRENT_INDEX_SCHEMA,
        )
        from loopforge.engine.models.migrations import migrate_run

        file_name = path.name
        schema_map = {
            "run.json": int(CURRENT_RUN_SCHEMA),
            "config.json": int(CURRENT_CONFIG_SCHEMA),
            "registry.json": int(CURRENT_REGISTRY_SCHEMA),
            "index.json": int(CURRENT_INDEX_SCHEMA),
        }
        target_schema = schema_map.get(file_name)
        if target_schema is None:
            return False, f"Unknown file type for migration: {file_name}"

        try:
            if file_name == "run.json":
                data = migrate_run(data)
            data["schema_version"] = target_schema
            self._store.write_object(path, data)
            return True, f"Migrated {file_name} to schema v{target_schema}"
        except Exception as exc:
            return False, f"Migration failed for {path}: {exc}"

    def _repair_current_run_id(self, config_path_str: str) -> tuple[bool, str]:
        config_path = Path(config_path_str)
        if not config_path.is_file():
            return False, f"Config file not found: {config_path}"

        data, diagnostic = safe_read_json(self._store, config_path)
        if data is None:
            return False, f"Cannot read config: {diagnostic}"

        old_run_id = data.get("current_run_id", "")
        data["current_run_id"] = None
        from loopforge.engine import utc_now as _utc_now
        data["updated_at"] = _utc_now()
        try:
            self._store.write_object(config_path, data)
            return True, f"Reset current_run_id from '{old_run_id}' to None in {config_path}"
        except Exception as exc:
            return False, f"Failed to write config: {exc}"

    def _repair_orphan_worktree(self, ws_path_str: str) -> tuple[bool, str]:
        import shutil

        ws_path = Path(ws_path_str)
        if not ws_path.exists():
            return True, f"Workspace already removed: {ws_path}"
        try:
            if (ws_path / ".git").is_file() or (ws_path / ".git").is_dir():
                try:
                    import subprocess
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(ws_path)],
                        check=False, capture_output=True, text=True,
                    )
                except Exception:
                    pass
            shutil.rmtree(ws_path, ignore_errors=True)
            return True, f"Removed orphan workspace: {ws_path}"
        except Exception as exc:
            return False, f"Failed to remove orphan workspace {ws_path}: {exc}"