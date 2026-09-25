"""Validate a retained verification patch against its recorded identity."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from loopforge.engine.path_resolvers import resolve_artifact


def patch_integrity_blockers(run_dir: Path, patch: dict[str, Any]) -> list[str]:
    """Return reasons the patch cannot represent the recorded verification."""

    blockers: list[str] = []
    path_value = patch.get("path")
    patch_path: Path | None = None
    if not isinstance(path_value, str) or not path_value.strip() or Path(path_value).is_absolute():
        blockers.append("verification patch path must be relative to the run directory.")
    else:
        try:
            patch_path = resolve_artifact(run_dir, path_value)
        except (OSError, RuntimeError, ValueError):
            blockers.append("verification patch path must remain within the run directory.")

    expected_sha256 = patch.get("sha256")
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in expected_sha256)
    ):
        blockers.append("verification patch requires a valid sha256.")
    expected_size = patch.get("size_bytes")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        blockers.append("verification patch requires a valid size_bytes.")

    if patch_path is None:
        return blockers
    digest = hashlib.sha256()
    actual_size = 0
    try:
        with patch_path.open("rb") as patch_file:
            while chunk := patch_file.read(1024 * 1024):
                digest.update(chunk)
                actual_size += len(chunk)
    except OSError:
        blockers.append("verification patch must be retained and readable.")
        return blockers

    if isinstance(expected_size, int) and not isinstance(expected_size, bool) and actual_size != expected_size:
        blockers.append("verification patch size differs from the verified size_bytes.")
    if isinstance(expected_sha256, str) and digest.hexdigest() != expected_sha256.lower():
        blockers.append("verification patch sha256 differs from the verified sha256.")
    return blockers
