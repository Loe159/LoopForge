"""Read-only navigation preferences, independent of workflow authority."""

from dataclasses import dataclass
import math
from pathlib import Path

from loopforge.engine.path_resolvers import resolve_artifact
from loopforge.engine.storage import DEFAULT_JSON_STORE


RUN_VIEWS = ("Live", "Context", "Changes", "Evidences")


@dataclass(frozen=True)
class RunReading:
    view: str = "Live"
    stage_id: str = ""
    session_id: str = ""
    mode: str = "Focused"
    following: bool = True
    scroll_y: float = 0
    cumulative: bool = False


def _scroll_position(value: object) -> float:
    position = float(value)
    if not math.isfinite(position):
        return 0.0
    return max(0.0, min(position, 10_000_000.0))


def load_reading(run_dir: Path | None) -> RunReading:
    if run_dir is None:
        return RunReading()
    try:
        data = DEFAULT_JSON_STORE.read_object(resolve_artifact(run_dir, "ui-reading.json"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            return RunReading()
        return RunReading(
            view=data["view"] if data.get("view") in RUN_VIEWS else "Live",
            stage_id=str(data.get("stage_id") or "")[:200],
            session_id=str(data.get("session_id") or "")[:500],
            mode=data["mode"] if data.get("mode") in {"Focused", "All", "Raw"} else "Focused",
            following=data.get("following", True) is not False,
            scroll_y=_scroll_position(data.get("scroll_y", 0)),
            cumulative=data.get("cumulative") is True,
        )
    except (OSError, ValueError, TypeError, KeyError):
        return RunReading()


def save_reading(run_dir: Path | None, reading: RunReading) -> None:
    if run_dir is None:
        return
    from dataclasses import asdict

    try:
        DEFAULT_JSON_STORE.write_object(
            resolve_artifact(run_dir, "ui-reading.json"),
            {"schema_version": 1, **asdict(reading)},
        )
    except (OSError, ValueError):
        # UI preferences must never block an engine operation.
        return
