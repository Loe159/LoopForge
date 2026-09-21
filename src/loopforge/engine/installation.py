"""Installation, update, and runtime utility helpers for LoopForge."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InstallationResult:
    source_root: Path
    ok: bool
    message: str
    diagnostics: dict[str, str]
    blockers: list[str]
    updated: bool


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def install_loopforge(
    *, update: bool = False, source_root: Path | None = None
) -> InstallationResult:
    """Install or upgrade LoopForge from its source tree via pip.

    ``update`` uses ``pip install --upgrade -e .`` to refresh an existing
    editable install.  There is no ``git pull`` step — the function relies on
    pip to obtain the latest version and does not assume a Git work-tree or
    remote.  Every external command is argument-based and its output is kept
    out of the result so an installer never echoes credentials from a
    configured package index or Git remote.
    """

    root = (source_root or repository_root()).resolve()
    diagnostics: dict[str, str] = {
        "python": ".".join(str(value) for value in sys.version_info[:3]),
        "source": (
            "available" if (root / "pyproject.toml").is_file() else "missing pyproject.toml"
        ),
        "package": (
            "available" if (root / "src" / "loopforge").is_dir() else "missing src/loopforge"
        ),
    }
    blockers: list[str] = []
    if sys.version_info < (3, 11):
        blockers.append("LoopForge requires Python 3.11 or later.")
    if diagnostics["source"] != "available":
        blockers.append(f"LoopForge source metadata was not found at {root}.")
    if diagnostics["package"] != "available":
        blockers.append(
            f"LoopForge package sources were not found at {root / 'src' / 'loopforge'}."
        )

    # Exempt: installation/bootstrap infrastructure, not check execution
    try:
        pip = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        pip = None
    diagnostics["pip"] = (
        "available" if pip is not None and pip.returncode == 0 else "unavailable"
    )
    if diagnostics["pip"] != "available":
        blockers.append("pip is unavailable for the current Python interpreter.")

    try:
        git = subprocess.run(
            ["git", "--version"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        git = None
    diagnostics["git"] = (
        "available" if git is not None and git.returncode == 0 else "unavailable"
    )
    if diagnostics["git"] != "available":
        blockers.append("Git is unavailable; LoopForge needs it for workspaces and verification.")

    if blockers:
        return InstallationResult(
            root,
            False,
            "LoopForge installation prerequisites are incomplete.",
            diagnostics,
            blockers,
            False,
        )

    if update:
        # Use pip to upgrade an already-installed LoopForge distribution.
        # This works regardless of whether the original install was from PyPI
        # or from a local editable checkout.  It does *not* assume a Git
        # work-tree or perform a ``git pull``.
        try:
            pip_upgrade = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "-e", "."],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            pip_upgrade = None
        diagnostics["pip_upgrade"] = (
            "updated" if pip_upgrade is not None and pip_upgrade.returncode == 0 else "failed"
        )
        if diagnostics["pip_upgrade"] == "failed":
            return InstallationResult(
                root,
                False,
                "LoopForge update failed.",
                diagnostics,
                ["`python -m pip install --upgrade -e .` failed."],
                False,
            )
    else:
        try:
            pip_upgrade = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-e", "."],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError:
            pip_upgrade = None
        diagnostics["pip_upgrade"] = (
            "installed" if pip_upgrade is not None and pip_upgrade.returncode == 0 else "failed"
        )
        if diagnostics["pip_upgrade"] == "failed":
            return InstallationResult(
                root,
                False,
                "LoopForge installation failed.",
                diagnostics,
                ["`python -m pip install -e .` failed."],
                False,
            )

    try:
        imports = subprocess.run(
            [
                sys.executable,
                "-c",
                "import loopforge, rich, textual",
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        imports = None
    diagnostics["runtime_dependencies"] = (
        "available" if imports is not None and imports.returncode == 0 else "failed"
    )

    scripts_dir = sysconfig.get_path("scripts")
    command_name = "loopforge.exe" if os.name == "nt" else "loopforge"
    command_path = Path(scripts_dir) / command_name if scripts_dir else None
    diagnostics["command"] = (
        str(command_path) if command_path and command_path.is_file() else "missing"
    )
    if diagnostics["runtime_dependencies"] != "available":
        blockers.append("LoopForge or one of its runtime dependencies could not be imported.")
    if diagnostics["command"] == "missing":
        blockers.append("The installed LoopForge command entry point was not found.")
    if blockers:
        return InstallationResult(
            root,
            False,
            "LoopForge was installed but its verification failed.",
            diagnostics,
            blockers,
            update,
        )
    return InstallationResult(
        root,
        True,
        "LoopForge is installed and ready to use.",
        diagnostics,
        [],
        update,
    )


def local_implementation_adapter() -> Path:
    return Path(__file__).resolve().parents[1] / "adapters" / "local_implementation_adapter.py"


def imported_check(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "checks" / name


def default_diff_policy() -> Path:
    from loopforge.contracts import policy_path

    return policy_path("diff-policy.json")


def default_risk_policy() -> Path:
    from loopforge.contracts import policy_path

    return policy_path("risk-rules.json")


def isolated_process_module() -> Any:
    from loopforge.checks import isolated_process

    return isolated_process


def is_windows_app_execution_alias(path: Path) -> bool:
    normalized = str(path).replace("/", "\\").upper()
    return (
        "\\APPDATA\\LOCAL\\MICROSOFT\\WINDOWSAPPS\\" in normalized
        and path.parent.name.casefold() == "windowsapps"
    )


def usable_python_executable() -> str:
    candidates: list[str | None] = [
        os.environ.get("LOOPFORGE_PYTHON"),
        sys.executable,
        getattr(sys, "_base_executable", None),
        shutil.which("python"),
        shutil.which("python3"),
        shutil.which("py"),
        str(
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "python"
            / "python.exe"
        ),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.is_absolute():
            resolved = shutil.which(candidate)
            if resolved is None:
                continue
            path = Path(resolved)
        if path.is_file() and not is_windows_app_execution_alias(path):
            return str(path)
    raise RuntimeError(
        "no usable Python executable found for isolated adapter execution; "
        "set LOOPFORGE_PYTHON to a real python.exe outside WindowsApps."
    )


def loopforge_module_command(module: str, arguments: list[str]) -> list[str]:
    """Run a packaged LoopForge module with an isolated Python runtime.

    The Codex-bundled Python is deliberately usable even when it does not own
    LoopForge's site-packages.  Bootstrap the installed or source package
    explicitly so internal checks and the implementation wrapper use the same
    runtime contract.
    """
    source_root = Path(__file__).resolve().parents[2]
    bootstrap = (
        "import runpy, sys; "
        f"sys.path.insert(0, {str(source_root)!r}); "
        f"runpy.run_module({module!r}, run_name='__main__')"
    )
    return [usable_python_executable(), "-c", bootstrap, *arguments]
