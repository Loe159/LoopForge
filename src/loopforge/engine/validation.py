"""Cached, in-process validation for legacy compatibility artifacts."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from loopforge.engine.storage import DEFAULT_JSON_STORE


VALIDATION_CACHE_FILE = ".validation-cache.json"
VALIDATION_CACHE_SCHEMA_VERSION = 1
VALIDATOR_VERSION = 1
MAX_VALIDATION_ERRORS = 32
MAX_ERROR_TEXT_LENGTH = 512


def validation_cache_path(artifact_dir: Path) -> Path:
    """Return the derived-data cache stored beside the compatibility artifacts."""

    return artifact_dir.parent / f".{artifact_dir.name}{VALIDATION_CACHE_FILE}"


def artifact_signature(artifact_dir: Path, artifact_names: tuple[str, ...]) -> dict[str, Any]:
    """Build a cheap metadata signature for contract inputs and their directory."""

    try:
        directory_stat = artifact_dir.stat()
        directory = {
            "state": "directory" if artifact_dir.is_dir() else "not_directory",
            "mtime_ns": directory_stat.st_mtime_ns,
        }
    except OSError as error:
        directory = {
            "state": "unavailable",
            "error": str(error)[:MAX_ERROR_TEXT_LENGTH],
        }

    files: list[dict[str, Any]] = []
    for name in sorted(set(artifact_names)):
        path = artifact_dir / name
        try:
            stat = path.stat()
        except OSError as error:
            files.append(
                {
                    "name": name,
                    "state": "unavailable",
                    "error": str(error)[:MAX_ERROR_TEXT_LENGTH],
                }
            )
            continue
        files.append(
            {
                "name": name,
                "state": "file" if path.is_file() else "missing",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    encoded = repr(files).encode("utf-8")
    return {
        "algorithm": "sha256-metadata-v1",
        "digest": hashlib.sha256(encoded).hexdigest(),
        "directory": directory,
        "files": files,
    }


def _bounded_errors(errors: object) -> list[dict[str, str]]:
    if not isinstance(errors, list):
        return []
    bounded: list[dict[str, str]] = []
    for item in errors[:MAX_VALIDATION_ERRORS]:
        if isinstance(item, dict):
            bounded.append(
                {
                    "artifact": str(item.get("artifact") or "*"),
                    "rule": str(item.get("rule") or "validation"),
                    "message": str(item.get("message") or "")[:MAX_ERROR_TEXT_LENGTH],
                }
            )
        else:
            bounded.append(
                {
                    "artifact": "*",
                    "rule": "validation",
                    "message": str(item)[:MAX_ERROR_TEXT_LENGTH],
                }
            )
    return bounded


def _unchecked_state(artifact_dir: Path, message: str) -> dict[str, Any]:
    return {
        "status": "unchecked",
        "artifact_dir": str(artifact_dir),
        "errors": [
            {
                "artifact": "*",
                "rule": "validation",
                "message": message[:MAX_ERROR_TEXT_LENGTH],
            }
        ],
    }


def refresh_legacy_validation_cache(
    artifact_dir: Path,
    artifact_names: tuple[str, ...],
    *,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    """Validate artifacts in process and atomically publish their derived cache."""

    # Import lazily: the legacy command module delegates here in its ``main``.
    from loopforge.checks import validate_artifacts
    from loopforge.engine import utc_now

    try:
        selected_contract = contract_path or validate_artifacts.policy_path(
            "artifact-contract.json"
        )
        contract = validate_artifacts.load_contract(selected_contract)
        result = validate_artifacts.validate_directory(artifact_dir, contract, False)
        status = "valid" if result["valid"] else "invalid"
        cache = {
            "schema_version": VALIDATION_CACHE_SCHEMA_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "artifact_signature": artifact_signature(artifact_dir, artifact_names),
            "status": status,
            "errors": _bounded_errors(result.get("errors")),
            "validation_timestamp": utc_now(),
        }
    except (OSError, UnicodeError, ValueError) as error:
        cache = {
            "schema_version": VALIDATION_CACHE_SCHEMA_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "artifact_signature": artifact_signature(artifact_dir, artifact_names),
            "status": "unchecked",
            "errors": _unchecked_state(artifact_dir, str(error))["errors"],
            "validation_timestamp": utc_now(),
        }
    DEFAULT_JSON_STORE.write_object(validation_cache_path(artifact_dir), cache)
    return cache


def cached_legacy_validation_state(
    artifact_dir: Path,
    artifact_names: tuple[str, ...],
) -> dict[str, Any]:
    """Read a validation result without validating, writing, or starting a process."""

    cache_path = validation_cache_path(artifact_dir)
    try:
        cache = DEFAULT_JSON_STORE.read_object(cache_path)
    except FileNotFoundError:
        return _unchecked_state(artifact_dir, f"validation cache not found: {cache_path}")
    except (OSError, UnicodeError, ValueError) as error:
        return _unchecked_state(artifact_dir, f"validation cache could not be read: {error}")

    if (
        cache.get("schema_version") != VALIDATION_CACHE_SCHEMA_VERSION
        or cache.get("validator_version") != VALIDATOR_VERSION
        or cache.get("status") not in {"valid", "invalid", "unchecked"}
    ):
        return _unchecked_state(
            artifact_dir,
            "validation cache has an unsupported schema or validator version",
        )

    current_signature = artifact_signature(artifact_dir, artifact_names)
    if cache.get("artifact_signature") != current_signature:
        return {
            "status": "stale",
            "artifact_dir": str(artifact_dir),
            "errors": [
                {
                    "artifact": "*",
                    "rule": "artifact_signature",
                    "message": "legacy artifacts changed since the cached validation.",
                }
            ],
            "validation_timestamp": cache.get("validation_timestamp"),
        }

    return {
        "status": cache["status"],
        "artifact_dir": str(artifact_dir),
        "errors": _bounded_errors(cache.get("errors")),
        "validation_timestamp": cache.get("validation_timestamp"),
    }
