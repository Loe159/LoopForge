"""Central terminal capability detection for LoopForge.

This module is the **single** place that decides rich/plain/ascii/mono and
terminal width.  All consumers (``TerminalRenderer.set_mode``,
``LoopForgeApp._set_width_class``, ``interactive.py``) delegate here instead
of scattering TTY / colour / width checks across the codebase.

Env vars honoured
-----------------
``NO_COLOR`` / ``LOOPFORGE_NO_COLOR`` / ``TERM=dumb`` → suppress colour.
``FORCE_COLOR``                            → enable Rich even without a TTY.
``COLUMNS``                                → override detected width.
``LOOPFORGE_ASCII`` (= ``1``/``true``/``yes``) → ASCII-only glyphs (no braille).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

try:
    import importlib.util as _ilu
    _RICH_AVAILABLE = _ilu.find_spec("rich") is not None
except Exception:  # pragma: no cover - defensive
    _RICH_AVAILABLE = False


@dataclass(frozen=True)
class TerminalCapabilities:
    """Immutable snapshot of what the output stream can render."""

    use_rich: bool       # Rich rendering is enabled (panels, tables, colours)
    no_color: bool       # All colour output is suppressed
    ascii_only: bool     # Glyphs must be ASCII-only (LOOPFORGE_ASCII)
    is_tty: bool         # The output stream is a terminal
    width: int           # Detected/overridden terminal width in columns
    width_class: str     # CSS class for responsive layouts (width-60/80/120/160)


# ── width helpers ──────────────────────────────────────────────────────────

_WIDTH_BREAKPOINTS = (
    (80, "width-60"),
    (120, "width-80"),
    (160, "width-120"),
)


def width_class_for(width: int) -> str:
    """Return the responsive CSS class for a given terminal width.

    Breakpoints: < 80 → width-60, < 120 → width-80,
    < 160 → width-120, else width-160.
    """

    for threshold, css_class in _WIDTH_BREAKPOINTS:
        if width < threshold:
            return css_class
    return "width-160"


def detect_width(output: object, *, override: int | None = None) -> int:
    """Determine the terminal width from override, ``COLUMNS``, or the stream."""

    if override is not None and override > 0:
        return override
    columns = os.environ.get("COLUMNS")
    if columns and columns.isdigit():
        return int(columns)
    try:
        return shutil.get_terminal_size().columns
    except (OSError, ValueError):
        return 80


# ── capability detection ───────────────────────────────────────────────────


def _env_truthy(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}


def detect_capabilities(
    output: object,
    *,
    mode: str = "auto",
    no_color: bool = False,
    plain: bool = False,
    width_override: int | None = None,
    rich_available: bool | None = None,
) -> TerminalCapabilities:
    """Return the terminal capabilities for *output*.

    Parameters mirror the existing ``TerminalRenderer`` constructor:

    * ``mode``  – ``"auto"`` (default), ``"rich"``, or ``"plain"``.
    * ``no_color`` – explicit ``--no-color`` flag.
    * ``plain`` – explicit ``--plain`` flag (implies no colour, no Rich).
    * ``width_override`` – forced width (e.g. from a Textual resize event).
    * ``rich_available`` – cache of ``importlib`` check (defaults to auto-detect).
    """

    rich_ok = _RICH_AVAILABLE if rich_available is None else rich_available

    env_no_color = (
        os.environ.get("NO_COLOR") is not None
        or os.environ.get("LOOPFORGE_NO_COLOR") is not None
        or os.environ.get("TERM") == "dumb"
    )
    effective_no_color = bool(no_color or plain or env_no_color)

    force_color = os.environ.get("FORCE_COLOR") is not None and not effective_no_color

    is_tty = hasattr(output, "isatty") and output.isatty()

    auto_rich = (
        mode == "auto"
        and rich_ok
        and not plain
        and (is_tty or force_color)
        and not effective_no_color
    )
    explicit_rich = mode == "rich" and rich_ok and not effective_no_color and not plain
    use_rich = explicit_rich or auto_rich

    ascii_only = _env_truthy("LOOPFORGE_ASCII")

    width = detect_width(output, override=width_override)

    return TerminalCapabilities(
        use_rich=use_rich,
        no_color=effective_no_color,
        ascii_only=ascii_only,
        is_tty=is_tty,
        width=width,
        width_class=width_class_for(width),
    )
