"""Schema migration functions for all persisted LoopForge structures."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Callable

from loopforge.engine.models.schema import (
    CURRENT_RUN_SCHEMA,
    CURRENT_CONFIG_SCHEMA,
    CURRENT_REGISTRY_SCHEMA,
    CURRENT_INDEX_SCHEMA,
    SchemaVersion,
)

logger = logging.getLogger(__name__)


def _detect_version(data: dict[str, Any], default: int = 1) -> int:
    raw = data.get("schema_version")
    if raw is not None:
        return int(raw)
    return default


def _backup_file(file_path: Path, version: int) -> None:
    try:
        if not file_path.exists():
            return
        backup_path = file_path.with_suffix(file_path.suffix + f".v{version}.bak")
        shutil.copy2(file_path, backup_path)
    except OSError:
        logger.debug("Could not create backup for %s", file_path)


def _chain_migrations(
    data: dict[str, Any],
    migrations: dict[int, Callable[[dict], dict]],
    target: int,
    context_name: str,
    file_path: Path | None,
    default_version: int = 1,
) -> dict[str, Any]:
    version = _detect_version(data, default=default_version)
    if version >= target:
        return data
    result = dict(data)
    current_schema_version = version
    while current_schema_version < target:
        migrate_fn = migrations.get(current_schema_version)
        if migrate_fn is None:
            logger.debug(
                "No migration from schema_version %d for %s",
                current_schema_version,
                context_name,
            )
            break
        logger.warning(
            "Migrating %s from schema_version %d to %d",
            context_name,
            current_schema_version,
            current_schema_version + 1,
        )
        if file_path is not None:
            _backup_file(file_path, current_schema_version)
        result = migrate_fn(result)
        current_schema_version = _detect_version(result, default=current_schema_version + 1)
    return result


def migrate_v1_run_to_v2(run: dict[str, Any]) -> dict[str, Any]:
    if _detect_version(run, default=1) >= SchemaVersion.V2:
        return run
    updated = dict(run)
    updated["schema_version"] = int(SchemaVersion.V2)
    return updated


def migrate_v1_config_to_v2(config: dict[str, Any]) -> dict[str, Any]:
    if _detect_version(config, default=1) >= SchemaVersion.V2:
        return config
    updated = dict(config)
    updated["schema_version"] = int(SchemaVersion.V2)
    return updated


def migrate_v1_registry_to_v2(registry: dict[str, Any]) -> dict[str, Any]:
    if _detect_version(registry, default=1) >= SchemaVersion.V2:
        return registry
    updated = dict(registry)
    updated["schema_version"] = int(SchemaVersion.V2)
    return updated


def migrate_v1_index_to_v2(index: dict[str, Any]) -> dict[str, Any]:
    if _detect_version(index, default=1) >= SchemaVersion.V2:
        return index
    updated = dict(index)
    updated["schema_version"] = int(SchemaVersion.V2)
    return updated


MIGRATIONS: dict[int, Callable[[dict], dict]] = {
    1: migrate_v1_run_to_v2,
}


def migrate_run(run: dict[str, Any], file_path: Path | None = None) -> dict[str, Any]:
    return _chain_migrations(
        run,
        MIGRATIONS,
        target=int(CURRENT_RUN_SCHEMA),
        context_name="run",
        file_path=file_path,
        default_version=1,
    )


def migrate_config(config: dict[str, Any], file_path: Path | None = None) -> dict[str, Any]:
    return _chain_migrations(
        config,
        MIGRATIONS,
        target=int(CURRENT_CONFIG_SCHEMA),
        context_name="config",
        file_path=file_path,
        default_version=1,
    )


def migrate_registry(registry: dict[str, Any], file_path: Path | None = None) -> dict[str, Any]:
    return _chain_migrations(
        registry,
        MIGRATIONS,
        target=int(CURRENT_REGISTRY_SCHEMA),
        context_name="registry",
        file_path=file_path,
        default_version=1,
    )


def migrate_index(index: dict[str, Any], file_path: Path | None = None) -> dict[str, Any]:
    return _chain_migrations(
        index,
        MIGRATIONS,
        target=int(CURRENT_INDEX_SCHEMA),
        context_name="index",
        file_path=file_path,
        default_version=1,
    )