"""File recovery and corruption handling for LoopForge."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from .storage import JsonStore

logger = logging.getLogger(__name__)


def quarantine_corrupt_file(path: Path) -> Path:
    """Rename a corrupt file to {path}.corrupt.{timestamp}.

    The original file is moved, not deleted, preserving evidence.
    Returns the quarantine path.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine_path = path.with_suffix(path.suffix + f".corrupt.{timestamp}")
    shutil.move(str(path), str(quarantine_path))
    logger.error("Quarantined corrupt file: %s → %s", path, quarantine_path)
    return quarantine_path


def safe_read_json(store: JsonStore, path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """Safely read a JSON file, quarantining it on failure.

    Returns:
        (data, None) on success
        (None, diagnostic_message) on failure — the corrupt file is quarantined
    """
    if not path.exists():
        return None, f"File not found: {path}"
    try:
        data = store.read_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        quarantine_path = quarantine_corrupt_file(path)
        return None, f"Corrupt file quarantined: {quarantine_path}. Original error: {exc}"
    return data, None