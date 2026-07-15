"""Paths to packaged deterministic contracts."""

from __future__ import annotations

from pathlib import Path


def policy_path(name: str) -> Path:
    """Return a packaged policy file by name."""
    return Path(__file__).resolve().parent / "policies" / name


def schema_path(name: str) -> Path:
    """Return a packaged schema file by name."""
    return Path(__file__).resolve().parent / "schemas" / name
