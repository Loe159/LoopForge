"""Project configuration, initialization, opening, and archival."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loopforge.engine import projects as project_registry
from loopforge.engine.path_resolvers import resolve_run_dir, validate_identifier
from loopforge.engine.storage import DEFAULT_JSON_STORE
from loopforge.engine.models.schema import CURRENT_CONFIG_SCHEMA
from loopforge.engine.models.scope import ActionScope


@dataclass(frozen=True)
class InitResult:
    project_dir: Path
    config_path: Path
    config: dict[str, Any]
    created: bool
    repaired: bool
    registration: project_registry.ProjectRegistration | None = None
    migrated_run_root: Path | None = None


@dataclass(frozen=True)
class OpenProjectResult:
    project_dir: Path | None
    init: InitResult | None
    ok: bool
    message: str
    blockers: list[str]


@dataclass(frozen=True)
class ConfigUpdateResult:
    project_dir: Path
    config_path: Path
    config: dict[str, Any] | None
    ok: bool
    message: str
    blockers: list[str]


def new_config(
    project_dir: Path,
    profile: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    from loopforge.engine import (
        DEFAULT_ADAPTER,
        DEFAULT_PROFILE,
        loopforge_home,
        normalize_profile,
        project_name,
        utc_now,
    )

    if profile is None:
        profile = DEFAULT_PROFILE
    now = utc_now()
    normalized_profile = normalize_profile(profile)
    project_id = project_registry.new_project_id()
    storage_root = project_registry.storage_root(loopforge_home(home=home), project_id)
    return {
        "schema_version": int(CURRENT_CONFIG_SCHEMA),
        "project_id": project_id,
        "project_name": project_name(project_dir),
        "profile": normalized_profile,
        "run_root": str(storage_root / "runs"),
        "current_run_id": None,
        "default_adapter": DEFAULT_ADAPTER,
        "default_adapter_args": [],
        "created_at": now,
        "updated_at": now,
    }


def normalize_config(
    project_dir: Path,
    existing: dict[str, Any],
    profile: str | None = None,
    home: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    from loopforge.engine import (
        CONFIG_KEYS,
        DEFAULT_ADAPTER,
        DEFAULT_PROFILE,
        SUPPORTED_ADAPTERS,
        loopforge_home,
        normalize_profile,
        project_name,
        utc_now,
    )

    if profile is None:
        profile = DEFAULT_PROFILE
    config = dict(existing)
    now = utc_now()
    if "schema_version" not in config:
        config["schema_version"] = int(CURRENT_CONFIG_SCHEMA)
    if "created_at" not in config:
        config["created_at"] = now
    if "current_run_id" not in config:
        config["current_run_id"] = None
    if config.get("default_adapter") not in SUPPORTED_ADAPTERS:
        config["default_adapter"] = DEFAULT_ADAPTER
    if not isinstance(config.get("default_adapter_args"), list):
        config["default_adapter_args"] = []
    else:
        config["default_adapter_args"] = [
            str(value) for value in config["default_adapter_args"]
        ]
    if "project_name" not in config:
        config["project_name"] = project_name(project_dir)
    if not isinstance(config.get("project_id"), str) or not config["project_id"].strip():
        config["project_id"] = project_registry.new_project_id()
    normalized_profile = normalize_profile(config.get("profile", profile))
    if config.get("profile") != normalized_profile:
        config["profile"] = normalized_profile
    home_root = loopforge_home(home=home)
    if "run_root" not in config:
        config["run_root"] = str(
            project_registry.storage_root(
                home_root, str(config["project_id"])
            )
            / "runs"
        )
    elif home is not None:
        raw = str(config["run_root"])
        resolved = Path(raw).expanduser().resolve()
        home_resolved = home_root.resolve()
        try:
            resolved.relative_to(home_resolved)
        except ValueError:
            raise ValueError(
                f"Run root {raw} is outside the LoopForge home directory "
                f"({home_root}). Use `loopforge doctor` to migrate legacy "
                f"external run roots."
            )
    if "updated_at" not in config:
        config["updated_at"] = now

    repaired = any(config.get(key) != existing.get(key) for key in CONFIG_KEYS)
    if repaired:
        config["updated_at"] = now
    return config, repaired


def initialize_project(
    project_dir: Path,
    profile: str | None = None,
    home: Path | None = None,
) -> InitResult:
    from loopforge.engine import (
        DEFAULT_PROFILE,
        _sync_project_indexes,
        ensure_project_memory,
        ensure_templates,
        loopforge_home,
        project_config_path,
        read_json,
        write_json_atomic,
    )

    if profile is None:
        profile = DEFAULT_PROFILE
    project_dir = project_dir.resolve()
    config_path = project_config_path(project_dir)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_templates(project_dir)
    ensure_project_memory(project_dir)

    migrated_run_root: Path | None = None
    if config_path.exists():
        existing = read_json(config_path)
        config, repaired = normalize_config(
            project_dir,
            existing,
            profile=profile,
            home=home,
        )
        home_root = loopforge_home(home=home)
        target_root = project_registry.migration_target(home_root, str(config["project_id"]))
        previous_raw = existing.get("run_root")
        previous_run_root = (
            Path(previous_raw).expanduser()
            if isinstance(previous_raw, str) and previous_raw.strip()
            else None
        )
        if previous_run_root is not None and previous_run_root != target_root:
            if not target_root.exists():
                migrated_run_root = previous_run_root
            config["run_root"] = str(target_root)
            repaired = True
        if repaired:
            write_json_atomic(config_path, config)
        registration = project_registry.register_project(project_dir, config, home_root)
        if migrated_run_root is not None:
            try:
                _sync_project_indexes(project_dir, config, rebuild=True)
            except OSError:
                pass
        return InitResult(
            project_dir=project_dir,
            config_path=config_path,
            config=config,
            created=False,
            repaired=repaired,
            registration=registration,
            migrated_run_root=migrated_run_root,
        )

    config = new_config(project_dir, profile=profile, home=home)
    write_json_atomic(config_path, config)
    registration = project_registry.register_project(project_dir, config, loopforge_home(home=home))
    return InitResult(
        project_dir=project_dir,
        config_path=config_path,
        config=config,
        created=True,
        repaired=False,
        registration=registration,
    )


def open_project(
    project_or_path: str | None,
    *,
    current_project_dir: Path,
    home: Path | None = None,
    identity_resolution: str | None = None,
) -> OpenProjectResult:
    """Open or register a project, requiring an explicit duplicate-id decision."""

    from loopforge.engine import loopforge_home, write_json_atomic

    home_root = loopforge_home(home=home)
    target: Path | None = current_project_dir.resolve()
    requested = str(project_or_path or "").strip()
    if requested:
        candidate = Path(requested).expanduser()
        if candidate.exists():
            target = candidate.resolve()
        else:
            matches = [
                record
                for record in project_registry.registered_projects(home_root)
                if requested in {str(record.get("project_id") or ""), str(record.get("name") or "")}
            ]
            if len(matches) != 1:
                return OpenProjectResult(
                    None,
                    None,
                    False,
                    "LoopForge could not resolve the project.",
                    [f"no unique registered project matches: {requested}"],
                )
            target = Path(str(matches[0]["path"])).expanduser().resolve()
    if target is None or not target.is_dir():
        return OpenProjectResult(
            target,
            None,
            False,
            "LoopForge could not open the project.",
            [f"project directory does not exist: {target}"],
        )
    result = initialize_project(target, home=home)
    registration = result.registration
    if registration is not None and not registration.ok:
        if identity_resolution == "moved":
            registration = project_registry.register_project(
                target, result.config, home_root, allow_move=True
            )
            result = InitResult(
                result.project_dir,
                result.config_path,
                result.config,
                result.created,
                result.repaired,
                registration,
                result.migrated_run_root,
            )
        elif identity_resolution == "clone":
            config = project_registry.regenerate_project_identity(target, result.config, home_root)
            write_json_atomic(result.config_path, config)
            registration = project_registry.register_project(target, config, home_root)
            result = InitResult(
                result.project_dir,
                result.config_path,
                config,
                result.created,
                True,
                registration,
                result.migrated_run_root,
            )
        else:
            conflict = registration.conflict_path
            return OpenProjectResult(
                target,
                result,
                False,
                "Project identity needs confirmation.",
                [
                    f"project id {registration.project_id} is already registered at {conflict}",
                    "Use `loopforge open <path> --moved` after moving a repository, or `--clone` for a copy.",
                ],
            )
    return OpenProjectResult(target, result, True, "Project opened.", [])


def update_project_config(project_dir: Path, updates: dict[str, Any]) -> ConfigUpdateResult:
    from loopforge.engine import (
        current_status,
        persist_project_config,
        utc_now,
    )

    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=None,
            ok=False,
            message="LoopForge config update failed.",
            blockers=[status.next_step],
        )

    config = dict(status.config)
    for key, value in updates.items():
        config[key] = value
    config["updated_at"] = utc_now()
    normalized, _ = normalize_config(status.project_dir, config)
    persist_project_config(status.project_dir, status.config_path, normalized)
    return ConfigUpdateResult(
        project_dir=status.project_dir,
        config_path=status.config_path,
        config=normalized,
        ok=True,
        message=f"LoopForge config updated: {status.config_path}",
        blockers=[],
    )


def set_default_adapter(
    project_dir: Path,
    adapter: str,
    adapter_args: list[str] | None = None,
) -> ConfigUpdateResult:
    from loopforge.engine import SUPPORTED_ADAPTERS, project_config_path

    if adapter not in SUPPORTED_ADAPTERS:
        return ConfigUpdateResult(
            project_dir=project_dir.resolve(),
            config_path=project_config_path(project_dir.resolve()),
            config=None,
            ok=False,
            message="LoopForge adapter update failed.",
            blockers=[f"unsupported adapter: {adapter}"],
        )
    updates: dict[str, Any] = {"default_adapter": adapter}
    if adapter_args is not None:
        updates["default_adapter_args"] = [str(value) for value in adapter_args]
    return update_project_config(project_dir, updates)


def archive_run(project_dir: Path, run_id: str) -> ConfigUpdateResult:
    from loopforge.engine import (
        current_status,
        persist_run_json,
        read_json,
        utc_now,
    )

    validate_identifier(run_id, "run")

    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=None,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[status.next_step],
        )
    config_project_id = str(status.config.get("project_id") or "")
    scope = ActionScope(
        project_id=config_project_id,
        project_path=project_dir.resolve(),
        run_id=run_id,
    )
    scope.validate()
    run_root = Path(str(status.config["run_root"])).expanduser()
    run_dir = resolve_run_dir(run_root, run_id)
    run_json_path = run_dir / "run.json"
    if not run_json_path.exists():
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=status.config,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[f"run metadata not found: {run_json_path}"],
        )
    run = read_json(run_json_path)
    actual_id = str(run.get("run_id") or "")
    if actual_id != run_id:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=status.config,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[f"run id mismatch: run.json contains {actual_id}"],
        )
    updated_run = dict(run)
    updated_run["archived"] = True
    updated_run["archived_at"] = utc_now()
    persist_run_json(status.project_dir, run_json_path, updated_run)
    return ConfigUpdateResult(
        project_dir=status.project_dir,
        config_path=status.config_path,
        config=status.config,
        ok=True,
        message=f"LoopForge archived run: {run_id}",
        blockers=[],
    )


def archive_current_run(project_dir: Path) -> ConfigUpdateResult:
    from loopforge.engine import current_status

    status = current_status(project_dir)
    if not status.initialized or status.config is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=None,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[status.next_step],
        )
    if status.run is None or status.run_dir is None:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=status.config,
            ok=False,
            message="LoopForge archive failed.",
            blockers=[status.next_step],
        )
    run_id = str(status.run.get("run_id") or "")
    if not run_id:
        return ConfigUpdateResult(
            project_dir=status.project_dir,
            config_path=status.config_path,
            config=status.config,
            ok=False,
            message="LoopForge archive failed.",
            blockers=["current run has no id"],
        )
    return archive_run(project_dir, run_id)
