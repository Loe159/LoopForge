"""Schema version constants for all persisted LoopForge structures."""

from enum import IntEnum


class SchemaVersion(IntEnum):
    V1 = 1
    V2 = 2


CURRENT_RUN_SCHEMA = SchemaVersion.V2
CURRENT_CONFIG_SCHEMA = SchemaVersion.V2
CURRENT_REGISTRY_SCHEMA = SchemaVersion.V2
CURRENT_INDEX_SCHEMA = SchemaVersion.V2