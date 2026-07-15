"""Project-pack registry and contract validation for LoopForge."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopforge.engine.storage import JsonStore


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
        bundled_packs_root: Path | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.bundled_root = bundled_root
        self.store = store
        self.config_dir = config_dir
        self.default_pack = default_pack
        self.bundled_packs_root = bundled_packs_root

    def bundled_packs_path(self) -> Path:
        if self.bundled_packs_root is not None:
            return self.bundled_packs_root
        return self.bundled_root / self.config_dir / "packs"

    def roots(self) -> list[Path]:
        return [
            self.project_dir / self.config_dir / "packs",
            self.bundled_packs_path(),
        ]

    def file_candidates(self, pack: str, file_name: str) -> list[Path]:
        return [
            self.project_dir / self.config_dir / "packs" / pack / file_name,
            self.project_dir / self.config_dir / "packs" / f"{pack}.{file_name}",
            self.bundled_packs_path() / pack / file_name,
            self.bundled_packs_path() / f"{pack}.{file_name}",
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
        contract_names: set[str] = set()
        for root in reversed(self.roots()):
            if not root.exists():
                continue
            for path in sorted(root.glob("*/pack.json")):
                try:
                    contract = self.load_contract_from_path(path)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                contract_names.add(str(contract["name"]))
        contracts: list[dict[str, Any]] = []
        for name in sorted(contract_names):
            try:
                contracts.append(self.load_contract(name))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return contracts

    @staticmethod
    def _optional_relative_path(
        data: dict[str, Any],
        path: Path,
        field: str,
        default_name: str,
    ) -> tuple[str | None, bool]:
        raw = data.get(field)
        declared = field in data
        if raw is not None and (not isinstance(raw, str) or not raw.strip()):
            raise ValueError(f"{path} {field} must be a non-empty string")
        candidate = path.parent / (raw.strip() if isinstance(raw, str) else default_name)
        return (str(candidate) if declared or candidate.exists() else None, declared)

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
        extends = data.get("extends")
        if extends is not None and (not isinstance(extends, str) or not extends.strip()):
            raise ValueError(f"{path} extends must be a non-empty string")
        skill_file, skill_file_declared = self._optional_relative_path(
            data, path, "skill_file", "SKILL.md"
        )
        skills_dir, skills_dir_declared = self._optional_relative_path(
            data, path, "skills_dir", "skills"
        )
        agents_file, agents_file_declared = self._optional_relative_path(
            data, path, "agents_file", "agents.json"
        )
        permissions_file, permissions_file_declared = self._optional_relative_path(
            data, path, "permissions_file", "permissions.json"
        )
        workflow_file, workflow_file_declared = self._optional_relative_path(
            data, path, "workflow_file", "workflow.json"
        )
        return {
            "name": name,
            "version": version,
            "extends": extends.strip() if isinstance(extends, str) else None,
            "description": str(data.get("description") or "").strip(),
            "priority": priority,
            "source": str(path),
            "root": str(path.parent),
            "detection": detection,
            "skills": self.normalize_unique_strings(skills),
            "skill_file": skill_file,
            "skill_files": [skill_file] if skill_file else [],
            "skills_dir": skills_dir,
            "skills_dirs": [skills_dir] if skills_dir else [],
            "agents_file": agents_file,
            "permissions_file": permissions_file,
            "workflow_file": workflow_file,
            "checks_file": str(path.parent / str(data.get("checks_file") or "checks.json")),
            "protected_paths_file": str(
                path.parent / str(data.get("protected_paths_file") or "protected-paths.json")
            ),
            "memory_rules_file": str(
                path.parent / str(data.get("memory_rules_file") or "memory-rules.md")
            ),
            "memory": data.get("memory", {}) if isinstance(data.get("memory", {}), dict) else {},
            "inherited_from": [],
            "_declared": {
                "skill_file": skill_file_declared,
                "skills_dir": skills_dir_declared,
                "agents_file": agents_file_declared,
                "permissions_file": permissions_file_declared,
                "workflow_file": workflow_file_declared,
                "checks_file": "checks_file" in data,
                "protected_paths_file": "protected_paths_file" in data,
                "memory_rules_file": "memory_rules_file" in data,
            },
        }

    def _load_contract_manifest(self, pack: str) -> dict[str, Any]:
        for path in self.file_candidates(pack, "pack.json"):
            if path.exists():
                return self.load_contract_from_path(path)
        raise ValueError(f"project pack not found: {pack}")

    def _merge_contracts(
        self,
        parent: dict[str, Any],
        child: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(parent)
        merged.update(
            {
                key: child[key]
                for key in (
                    "name",
                    "version",
                    "extends",
                    "description",
                    "priority",
                    "source",
                    "root",
                    "detection",
                )
            }
        )
        merged["skills"] = self.normalize_unique_strings(
            [*parent.get("skills", []), *child.get("skills", [])]
        )
        merged["skill_files"] = self.normalize_unique_strings(
            [*parent.get("skill_files", []), *child.get("skill_files", [])]
        )
        merged["skills_dirs"] = self.normalize_unique_strings(
            [*parent.get("skills_dirs", []), *child.get("skills_dirs", [])]
        )
        declared = child.get("_declared", {})
        if not isinstance(declared, dict):
            declared = {}
        for field in (
            "skill_file",
            "skills_dir",
            "agents_file",
            "permissions_file",
            "workflow_file",
            "checks_file",
            "protected_paths_file",
            "memory_rules_file",
        ):
            if declared.get(field):
                merged[field] = child.get(field)
        merged["memory"] = {
            **(parent.get("memory", {}) if isinstance(parent.get("memory"), dict) else {}),
            **(child.get("memory", {}) if isinstance(child.get("memory"), dict) else {}),
        }
        merged["inherited_from"] = self.normalize_unique_strings(
            [*parent.get("inherited_from", []), str(parent["name"])]
        )
        merged["_declared"] = declared
        return merged

    def _load_contribution_object(
        self,
        contract: dict[str, Any],
        field: str,
        object_key: str,
    ) -> dict[str, Any]:
        value = contract.get(field)
        if not isinstance(value, str) or not value:
            empty: object = {} if object_key == "permission_sets" else []
            return {"source": None, object_key: empty}
        path = Path(value)
        if not path.exists():
            raise ValueError(f"{path} referenced by {contract['name']} does not exist")
        data = self.store.read_object(path)
        version = data.get("version", 1)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError(f"{path} version must be a positive integer")
        contribution = data.get(object_key)
        expected = dict if object_key == "permission_sets" else list
        if not isinstance(contribution, expected):
            raise ValueError(f"{path} must contain {object_key} as {expected.__name__}")
        return {"source": str(path), "version": version, object_key: contribution}

    def _hydrate_contract(self, contract: dict[str, Any]) -> dict[str, Any]:
        hydrated = dict(contract)
        skill_definition_files: list[str] = []
        skill_ids: set[str] = set()
        for value in contract.get("skills_dirs", []):
            skills_dir = Path(str(value))
            if not skills_dir.is_dir():
                raise ValueError(f"{skills_dir} referenced by {contract['name']} does not exist")
            definitions = sorted(skills_dir.glob("*/SKILL.md"))
            if not definitions:
                raise ValueError(f"{skills_dir} does not contain any */SKILL.md definitions")
            skill_definition_files.extend(str(path) for path in definitions)
            skill_ids.update(path.parent.name for path in definitions)
        if skill_ids:
            missing_skills = [
                skill for skill in contract.get("skills", []) if str(skill) not in skill_ids
            ]
            if missing_skills:
                raise ValueError(
                    f"{contract['name']} has skills without definitions: "
                    + ", ".join(str(skill) for skill in missing_skills)
                )

        agents_data = self._load_contribution_object(contract, "agents_file", "agents")
        permissions_data = self._load_contribution_object(
            contract, "permissions_file", "permission_sets"
        )
        workflow_data = self._load_contribution_object(contract, "workflow_file", "stages")
        agents = agents_data["agents"]
        permission_sets = permissions_data["permission_sets"]
        stages = workflow_data["stages"]

        for permission_id, boundary in permission_sets.items():
            if not isinstance(permission_id, str) or not permission_id.strip():
                raise ValueError(
                    f"{permissions_data['source']} permission set ids must be non-empty strings"
                )
            if not isinstance(boundary, dict):
                raise ValueError(
                    f"{permissions_data['source']} permission set {permission_id} must be an object"
                )

        agent_ids: set[str] = set()
        normalized_agents: list[dict[str, Any]] = []
        for index, agent in enumerate(agents, start=1):
            if not isinstance(agent, dict):
                raise ValueError(f"{agents_data['source']} agent {index} must be an object")
            agent_id = str(agent.get("id") or "").strip()
            if not agent_id or agent_id in agent_ids:
                raise ValueError(f"{agents_data['source']} agent {index} has an invalid id")
            stages_value = agent.get("stages", [])
            if not isinstance(stages_value, list) or not all(
                isinstance(stage, str) and stage.strip() for stage in stages_value
            ):
                raise ValueError(f"{agents_data['source']} agent {agent_id} stages are invalid")
            permission_set = str(agent.get("permission_set") or "").strip()
            if permission_set and permission_set not in permission_sets:
                raise ValueError(
                    f"{agents_data['source']} agent {agent_id} references unknown "
                    f"permission set {permission_set}"
                )
            prompt = str(agent.get("prompt") or "").strip()
            prompt_path = Path(str(agents_data["source"])).parent / prompt if prompt else None
            if prompt_path is not None and not prompt_path.is_file():
                raise ValueError(f"{prompt_path} referenced by agent {agent_id} does not exist")
            normalized_agents.append(
                {
                    **agent,
                    "id": agent_id,
                    "stages": [str(stage).strip() for stage in stages_value],
                    "permission_set": permission_set or None,
                    "prompt_path": str(prompt_path) if prompt_path is not None else None,
                }
            )
            agent_ids.add(agent_id)

        normalized_stages: list[dict[str, Any]] = []
        stage_ids: set[str] = set()
        for index, stage in enumerate(stages, start=1):
            if not isinstance(stage, dict):
                raise ValueError(f"{workflow_data['source']} stage {index} must be an object")
            stage_id = str(stage.get("id") or "").strip()
            if not stage_id or stage_id in stage_ids:
                raise ValueError(f"{workflow_data['source']} stage {index} has an invalid id")
            actor = stage.get("actor", {})
            if not isinstance(actor, dict):
                raise ValueError(f"{workflow_data['source']} stage {stage_id} actor is invalid")
            actor_type = str(actor.get("type") or "").strip()
            actor_id = str(actor.get("id") or "").strip()
            if actor_type not in {"agent", "deterministic"} or not actor_id:
                raise ValueError(
                    f"{workflow_data['source']} stage {stage_id} actor must define a valid type and id"
                )
            if actor_type == "agent" and actor_id not in agent_ids:
                raise ValueError(
                    f"{workflow_data['source']} stage {stage_id} references unknown agent "
                    f"{actor_id}"
                )
            normalized_stages.append({**stage, "id": stage_id})
            stage_ids.add(stage_id)

        agents_by_id = {str(agent["id"]): agent for agent in normalized_agents}
        for stage in normalized_stages:
            actor = stage["actor"]
            if actor.get("type") != "agent":
                continue
            agent = agents_by_id[str(actor["id"])]
            if stage["id"] not in agent["stages"]:
                raise ValueError(
                    f"{agents_data['source']} agent {agent['id']} does not declare "
                    f"workflow stage {stage['id']}"
                )

        hydrated["skill_definition_files"] = self.normalize_unique_strings(
            skill_definition_files
        )
        hydrated["agents"] = normalized_agents
        hydrated["permission_sets"] = permission_sets
        hydrated["workflow"] = normalized_stages
        hydrated["contribution_sources"] = {
            "agents": agents_data["source"],
            "permissions": permissions_data["source"],
            "workflow": workflow_data["source"],
        }
        hydrated.pop("_declared", None)
        return hydrated

    def _resolve_contract(self, pack: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if pack in stack:
            raise ValueError(f"pack inheritance cycle: {' -> '.join((*stack, pack))}")
        contract = self._load_contract_manifest(pack)
        parent_name = contract.get("extends")
        if isinstance(parent_name, str) and parent_name:
            parent = self._resolve_contract(parent_name, (*stack, pack))
            contract = self._merge_contracts(parent, contract)
        return contract

    def load_contract(self, pack: str) -> dict[str, Any]:
        return self._hydrate_contract(self._resolve_contract(pack, ()))

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
                "skill_files": [],
                "skills_dir": None,
                "skills_dirs": [],
                "agents_file": None,
                "permissions_file": None,
                "workflow_file": None,
                "agents": [],
                "permission_sets": {},
                "workflow": [],
                "contribution_sources": {},
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
