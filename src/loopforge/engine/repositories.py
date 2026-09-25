"""Thread-safe and process-safe repository layer for LoopForge persisted data.

Each repository wraps a JSON file with:
- Inter-process locking via FileLock
- Revision tracking (monotonic counter)
- Compare-and-swap semantics for updates
- Atomic read-modify-write operations
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .storage import JsonStore, DEFAULT_JSON_STORE
from .locking import FileLock, LockTimeoutError

logger = logging.getLogger(__name__)


class RevisionConflictError(Exception):
    """Raised when a CAS update fails due to revision mismatch."""


class BaseRepository:
    """Base class for JSON file repositories with locking and revision tracking."""

    def __init__(self, path: Path, store: JsonStore = DEFAULT_JSON_STORE,
                 lock_timeout: float = 5.0):
        self._path = Path(path)
        self._store = store
        self._lock = FileLock(self._path, timeout=lock_timeout)
        self._revision_field: str = "_revision"

    def read(self) -> dict[str, Any]:
        """Read the JSON file under lock, return the data dict.

        Returns an empty dict if the file does not exist.
        """
        try:
            self._lock.acquire()
        except LockTimeoutError:
            logger.error("Lock timeout reading %s", self._path)
            raise
        try:
            if not self._path.exists():
                return {}
            return self._store.read_object(self._path)
        finally:
            self._lock.release()

    def write(self, data: dict[str, Any], *, expected_revision: int | None = None) -> None:
        """Write under lock, rejecting a stale caller when a revision is supplied."""
        try:
            self._lock.acquire()
        except LockTimeoutError:
            logger.error("Lock timeout writing %s", self._path)
            raise
        try:
            current = self._store.read_object(self._path) if self._path.exists() else {}
            current_revision = current.get(self._revision_field, 0)
            if expected_revision is not None and current_revision != expected_revision:
                raise RevisionConflictError(
                    f"Stale {self._path}: expected revision {expected_revision}, "
                    f"got {current_revision}"
                )
            revision = current_revision + 1
            data[self._revision_field] = revision
            self._store.write_object(self._path, data)
        finally:
            self._lock.release()

    def update(self, update_fn: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        """Atomic read-lock-modify-write with CAS.

        Reads the current data, applies *update_fn*, writes back.
        If revision changed between read and write, raises
        :class:`RevisionConflictError`.

        Returns the updated data.
        """
        try:
            self._lock.acquire()
        except LockTimeoutError:
            logger.error("Lock timeout updating %s", self._path)
            raise
        try:
            if self._path.exists():
                current = self._store.read_object(self._path)
            else:
                current = {}
            original_revision = current.get(self._revision_field, 0)
            updated = update_fn(dict(current))
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists():
                re_read = self._store.read_object(self._path)
                if re_read.get(self._revision_field, 0) != original_revision:
                    raise RevisionConflictError(
                        f"CAS failed for {self._path}: "
                        f"expected revision {original_revision}, "
                        f"got {re_read.get(self._revision_field, 0)}"
                    )
            new_revision = original_revision + 1
            updated[self._revision_field] = new_revision
            self._store.write_object(self._path, updated)
            return updated
        finally:
            self._lock.release()


class RunRepository(BaseRepository):
    """Repository for run.json files."""

    def __init__(self, run_dir: Path, store: JsonStore = DEFAULT_JSON_STORE,
                 lock_timeout: float = 5.0):
        super().__init__(run_dir / "run.json", store, lock_timeout)
        self._revision_field = "run_revision"


class ConfigRepository(BaseRepository):
    """Repository for config.json files."""

    def __init__(self, config_dir: Path, store: JsonStore = DEFAULT_JSON_STORE,
                 lock_timeout: float = 5.0):
        super().__init__(config_dir / "config.json", store, lock_timeout)
        self._revision_field = "config_revision"


class RegistryRepository(BaseRepository):
    """Repository for registry.json files."""

    def __init__(self, registry_path: Path, store: JsonStore = DEFAULT_JSON_STORE,
                 lock_timeout: float = 5.0):
        super().__init__(registry_path, store, lock_timeout)
        self._revision_field = "registry_revision"


class IndexRepository(BaseRepository):
    """Repository for index.json files."""

    def __init__(self, index_path: Path, store: JsonStore = DEFAULT_JSON_STORE,
                 lock_timeout: float = 5.0):
        super().__init__(index_path, store, lock_timeout)
        self._revision_field = "index_revision"
