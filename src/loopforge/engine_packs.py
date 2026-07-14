"""Project-pack registry and contract validation for LoopForge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopforge.engine_storage import JsonStore


class PackRegistry:
    """Discover, validate, and load project-local or bundled pack contracts."""

    def __init__(
        self,
        project_dir: Path,
        *,
        bundled_root: Path,
        store: JsonStore,
        config_dir: str = ".loopforge",
        default_pack: str = "generic-code",
    ) -> None:
        self.project_dir = project_dir
        self.bundled_root = bundled_root
        self.store = store
        self.config_dir = config_dir
        self.default_pack = default_pack

    def roots(self) -> list[Path]:
        return [
            self.project_dir / self.config_dir / "packs",
            self.bundled_root / self.config_dir / "packs",
        ]

    def file_candidates(self, pack: str, file_name: str) -> list[Path]:
        return [
            self.project_dir / self.config_dir / "packs" / pack / file_name,
            self.project_dir / self.config_dir / "packs" / f"{pack}.{file_name}",
            self.bundled_root / self.config_dir / "packs" / pack / file_name,
            self.bundled_root / self.config_dir / "packs" / f"{pack}.{file_name}",
        ]

    @staticmethod
    def normalize_unique_strings(values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            stripped = value.strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            normalized.append(stripped)
        return normalized

    def discover_contracts(self) -> list[dict[str, Any]]:
        contracts_by_name: dict[str, dict[str, Any]] = {}
        for root in reversed(self.roots()):
            if not root.exists():
                continue
            for path in sorted(root.glob("*/pack.json")):
                try:
                    contract = self.load_contract_from_path(path)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                contracts_by_name[str(contract["name"])] = contract
        return sorted(contracts_by_name.values(), key=lambda item: str(item["name"]))

    def load_contract_from_path(self, path: Path) -> dict[str, Any]:
        data = self.store.read_object(path)
        name = str(data.get("name") or path.parent.name).strip()
        if not name:
            raise ValueError(f"{path} must define a pack name")
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError(f"{path} version must be a positive integer")
        detection = data.get("detection", {})
        if not isinstance(detection, dict):
            raise ValueError(f"{path} detection must be an object")
        skills = data.get("skills", [])
        if not isinstance(skills, list) or not all(isinstance(skill, str) for skill in skills):
            raise ValueError(f"{path} skills must be a list of strings")
        priority = data.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ValueError(f"{path} priority must be an integer")
        return {
            "name": name,
            "version": version,
            "description": str(data.get("description") or "").strip(),
            "priority": priority,
            "source": str(path),
            "root": str(path.parent),
            "detection": detection,
            "skills": self.normalize_unique_strings(skills),
            "skill_file": str(path.parent / str(data.get("skill_file") or "SKILL.md")),
            "checks_file": str(path.parent / str(data.get("checks_file") or "checks.json")),
            "protected_paths_file": str(
                path.parent / str(data.get("protected_paths_file") or "protected-paths.json")
            ),
            "memory_rules_file": str(
                path.parent / str(data.get("memory_rules_file") or "memory-rules.md")
            ),
            "memory": data.get("memory", {}) if isinstance(data.get("memory", {}), dict) else {},
        }

    def load_contract(self, pack: str) -> dict[str, Any]:
        for path in self.file_candidates(pack, "pack.json"):
            if path.exists():
                return self.load_contract_from_path(path)
        raise ValueError(f"project pack not found: {pack}")

    @staticmethod
    def detection_string_list(detection: dict[str, Any], key: str) -> list[str]:
        value = detection.get(key, [])
        if isinstance(value, str):
            return [value]
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()]

    def project_path_exists(self, relative_name: str) -> bool:
        return (self.project_dir / relative_name).exists()

    def project_glob_matches(self, pattern: str) -> bool:
        if not any(character in pattern for character in "*?["):
            return self.project_path_exists(pattern)
        try:
            return any(path.exists() for path in self.project_dir.glob(pattern))
        except ValueError:
            return False

    def detection_score(self, contract: dict[str, Any]) -> int:
        detection = contract.get("detection", {})
        if not isinstance(detection, dict):
            return 0
        all_files = self.detection_string_list(detection, "all_files")
        if all_files and not all(self.project_path_exists(name) for name in all_files):
            return 0
        all_dirs = self.detection_string_list(detection, "all_dirs")
        if all_dirs and not all((self.project_dir / name).is_dir() for name in all_dirs):
            return 0

        score = 0
        score += sum(
            20
            for name in self.detection_string_list(detection, "files_any")
            if self.project_path_exists(name)
        )
        score += sum(
            20
            for name in self.detection_string_list(detection, "dirs_any")
            if (self.project_dir / name).is_dir()
        )
        score += sum(
            10
            for pattern in self.detection_string_list(detection, "paths_any")
            if self.project_glob_matches(pattern)
        )
        if score <= 0:
            return 0
        return score + int(contract.get("priority", 0))

    def detect(self) -> dict[str, Any]:
        best: tuple[int, dict[str, Any]] | None = None
        for contract in self.discover_contracts():
            if contract["name"] == self.default_pack:
                continue
            score = self.detection_score(contract)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, contract)
        if best is not None:
            detected = dict(best[1])
            detected["detection_score"] = best[0]
            detected["detected"] = True
            return detected
        try:
            fallback = self.load_contract(self.default_pack)
        except ValueError:
            fallback = {
                "name": self.default_pack,
                "version": 1,
                "description": "Fallback generic code pack.",
                "priority": 0,
                "source": None,
                "root": None,
                "detection": {},
                "skills": [],
                "skill_file": None,
                "checks_file": None,
                "protected_paths_file": None,
                "memory_rules_file": None,
                "memory": {},
            }
        fallback["detection_score"] = 0
        fallback["detected"] = True
        return fallback

    def skill_entries(self, contract: dict[str, Any]) -> list[str]:
        skills = contract.get("skills", [])
        values = skills if isinstance(skills, list) else []
        skill_file = contract.get("skill_file")
        if isinstance(skill_file, str) and Path(skill_file).exists():
            values = [*values, f"pack:{contract['name']}:SKILL.md"]
        return self.normalize_unique_strings([str(value) for value in values])

    def check_paths(self, pack: str) -> list[Path]:
        return self.file_candidates(pack, "checks.json")

    def load_checks(self, pack: str) -> dict[str, Any]:
        for path in self.check_paths(pack):
            if not path.exists():
                continue
            data = self.store.read_object(path)
            checks = data.get("checks", [])
            if not isinstance(checks, list):
                raise ValueError(f"{path} must contain a checks list")
            normalized: list[dict[str, Any]] = []
            for index, check in enumerate(checks, start=1):
                if not isinstance(check, dict):
                    raise ValueError(f"{path} check {index} must be an object")
                name = str(check.get("name") or f"check-{index}").strip()
                command = check.get("command")
                if not isinstance(command, list) or not command or not all(
                    isinstance(part, str) and part for part in command
                ):
                    raise ValueError(f"{path} check {name} must define a non-empty command list")
                env = check.get("env", {})
                if not isinstance(env, dict) or not all(
                    isinstance(key, str) and isinstance(value, str)
                    for key, value in env.items()
                ):
                    raise ValueError(f"{path} check {name} env must be an object of strings")
                timeout = check.get("timeout_seconds", 300)
                if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
                    raise ValueError(f"{path} check {name} timeout_seconds must be positive")
                normalized.append(
                    {
                        "name": name,
                        "command": command,
                        "env": env,
                        "timeout_seconds": timeout,
                    }
                )
            return {"source": str(path), "checks": normalized}
        return {"source": None, "checks": []}

    def protected_path_paths(self, pack: str) -> list[Path]:
        return self.file_candidates(pack, "protected-paths.json")

    def load_protected_paths(self, pack: str) -> dict[str, Any]:
        for path in self.protected_path_paths(pack):
            if not path.exists():
                continue
            data = self.store.read_object(path)
            high = data.get("high_path_patterns", [])
            medium = data.get("medium_path_patterns", [])
            for field_name, value in (
                ("high_path_patterns", high),
                ("medium_path_patterns", medium),
            ):
                if not isinstance(value, list) or not all(
                    isinstance(pattern, str) for pattern in value
                ):
                    raise ValueError(f"{path} {field_name} must be a list of strings")
            return {
                "source": str(path),
                "high_path_patterns": high,
                "medium_path_patterns": medium,
            }
        return {
            "source": None,
            "high_path_patterns": [],
            "medium_path_patterns": [],
        }
