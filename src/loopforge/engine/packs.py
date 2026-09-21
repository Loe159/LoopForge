"""Project-pack registry and contract validation for LoopForge."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from loopforge.engine.storage import DEFAULT_JSON_STORE, JsonStore
from loopforge.engine.recovery import safe_read_json

logger = logging.getLogger(__name__)


class PackCycleError(ValueError):
    """Raised when pack inheritance forms a cycle."""


from loopforge.engine.models.pack import EffectivePackContract


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
        self._last_discovery_diagnostics: list[dict[str, str]] = []

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

    @staticmethod
    def _diagnose_contract_load_error(
        path: Path, error: Exception
    ) -> dict[str, str]:
        """Build a diagnostic dict for a pack.json that failed to load."""
        name = path.parent.name
        if isinstance(error, json.JSONDecodeError):
            return {
                "level": "error",
                "pack_name": name,
                "issue": "pack.json is not valid JSON",
                "detail": str(error),
                "action": f"Fix JSON syntax in {path} or remove the pack directory.",
            }
        if isinstance(error, ValueError):
            message = str(error)
            return {
                "level": "error",
                "pack_name": name,
                "issue": "pack.json is malformed",
                "detail": message,
                "action": f"Correct the validation error in {path}.",
            }
        return {
            "level": "error",
            "pack_name": name,
            "issue": "pack.json could not be read",
            "detail": str(error),
            "action": f"Check file permissions for {path}.",
        }

    def discover_contracts(
        self, *, collect_diagnostics: bool = False
    ) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, str]] = []
        contract_names: set[str] = set()
        for root in reversed(self.roots()):
            if not root.exists():
                continue
            for path in sorted(root.glob("*/pack.json")):
                try:
                    contract = self.load_contract_from_path(path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    diagnostic = self._diagnose_contract_load_error(path, exc)
                    diagnostics.append(diagnostic)
                    logger.warning(
                        "Pack at %s ignored: %s",
                        path,
                        diagnostic["detail"],
                    )
                    continue
                contract_names.add(str(contract["name"]))
        contracts: list[dict[str, Any]] = []
        for name in sorted(contract_names):
            try:
                contracts.append(self.load_contract(name))
            except PackCycleError as exc:
                diagnostics.append({
                    "level": "error",
                    "pack_name": name,
                    "issue": "cyclic pack inheritance",
                    "detail": str(exc),
                    "action": "Remove or rewire the extends chain to break the cycle.",
                })
                logger.warning("Pack %s ignored: cyclic inheritance — %s", name, exc)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                diagnostic = {
                    "level": "error",
                    "pack_name": name,
                    "issue": "pack could not be resolved",
                    "detail": str(exc),
                    "action": f"Check pack.json for '{name}' and its inherited packs.",
                }
                diagnostics.append(diagnostic)
                logger.warning(
                    "Pack %s ignored: %s",
                    name,
                    diagnostic["detail"],
                )
        if collect_diagnostics or diagnostics:
            self._last_discovery_diagnostics = diagnostics
        else:
            self._last_discovery_diagnostics = []
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

    @staticmethod
    def _compute_content_hash(data: dict[str, Any] | list[Any]) -> str:
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

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
        hydrated["contract_hash"] = self._compute_content_hash(hydrated)
        return hydrated

    def _resolve_contract(self, pack: str, stack: tuple[str, ...]) -> dict[str, Any]:
        if pack in stack:
            raise PackCycleError(f"pack inheritance cycle: {' -> '.join((*stack, pack))}")
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
                entry: dict[str, Any] = {
                    "name": name,
                    "command": command,
                    "env": env,
                    "timeout_seconds": timeout,
                }
                criterion = check.get("criterion")
                if isinstance(criterion, str) and criterion.strip():
                    entry["criterion"] = criterion.strip()
                normalized.append(entry)
            result = {"source": str(path), "checks": normalized}
            result["content_hash"] = PackRegistry._compute_content_hash(normalized)
            return result
        return {"source": None, "checks": [], "content_hash": ""}

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


def _hash_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode()
    ).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _load_memory_rules_text(registry: PackRegistry, pack_name: str) -> str:
    try:
        contract = registry.load_contract(pack_name)
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    rules_file = contract.get("memory_rules_file")
    if not isinstance(rules_file, str) or not rules_file:
        return ""
    rules_path = Path(rules_file)
    if not rules_path.is_file():
        return ""
    try:
        return rules_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _resolve_agents(
    agents_raw: list[dict],
    registry: PackRegistry,
    pack_name: str,
) -> list[dict]:
    resolved: list[dict] = []
    for agent in agents_raw:
        entry = dict(agent)
        if not isinstance(entry.get("prompt"), str) or not entry.get("prompt", "").strip():
            prompt_path = entry.get("prompt_path")
            if isinstance(prompt_path, str) and prompt_path:
                try:
                    entry["prompt"] = Path(prompt_path).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    entry["prompt"] = ""
        resolved.append(entry)
    return resolved


def freeze_pack_contract(
    project_dir: Path,
    pack_name: str,
    registry: PackRegistry | None = None,
    *,
    detection_mode: str = "",
    detection_score: int = 0,
) -> EffectivePackContract:
    """Hydrate and freeze the complete pack contract.

    Loads all pack assets, computes content hashes, and returns
    an immutable EffectivePackContract suitable for storing on a run.
    """
    if registry is None:
        from loopforge.engine import repository_root as _repo_root

        registry = PackRegistry(
            project_dir,
            bundled_root=_repo_root(),
            bundled_packs_root=Path(__file__).resolve().parents[1] / "packs",
            store=DEFAULT_JSON_STORE,
            config_dir=".loopforge",
            default_pack="generic-code",
        )

    contract = registry.load_contract(pack_name)
    if contract is None:
        raise ValueError(f"Pack '{pack_name}' not found or invalid")

    checks_data = registry.load_checks(pack_name)
    checks = checks_data.get("checks", [])

    protected_data = registry.load_protected_paths(pack_name)
    protected: list[dict] = []
    for severity in ("high", "medium"):
        key = f"{severity}_path_patterns"
        for pattern in protected_data.get(key, []):
            protected.append({"severity": severity, "pattern": pattern})

    memory_rules = _load_memory_rules_text(registry, pack_name)
    permissions = contract.get("permission_sets", {})
    agents_raw = contract.get("agents", [])
    workflow = contract.get("workflow", [])
    skills = contract.get("skills", [])

    agents = _resolve_agents(agents_raw, registry, pack_name)

    checks_hash = _hash_obj(checks)
    protected_hash = _hash_obj(protected)
    memory_hash = _hash_text(memory_rules)

    global_hash_input = json.dumps(
        {
            "checks": checks_hash,
            "protected_paths": protected_hash,
            "memory_rules": memory_hash,
            "permissions": _hash_obj(permissions),
            "agents": _hash_obj(agents),
            "workflow": _hash_obj(workflow),
            "skills": _hash_obj(skills),
        },
        sort_keys=True,
    ).encode()

    contract_hash = hashlib.sha256(global_hash_input).hexdigest()
    skills_hash = hashlib.sha256(
        json.dumps(skills, sort_keys=True).encode()
    ).hexdigest()

    return EffectivePackContract(
        name=pack_name,
        version=contract.get("version", 1),
        description=contract.get("description", ""),
        checks=checks,
        checks_content_hash=checks_hash,
        checks_source=checks_data.get("source"),
        protected_paths=protected,
        protected_paths_content_hash=protected_hash,
        memory_rules=memory_rules,
        memory_rules_hash=memory_hash,
        permissions=permissions,
        agents=agents,
        workflow=workflow,
        skills=skills,
        detection=detection_mode,
        detection_score=detection_score,
        contract_hash=contract_hash,
        skills_content_hash=skills_hash,
        frozen_at=datetime.now(timezone.utc).isoformat(),
        source=contract.get("source"),
        inherited_from=contract.get("inherited_from", []),
    )


def diagnose_pack_issues(
    project_dir: Path,
    *,
    registry: PackRegistry | None = None,
) -> list[dict[str, str]]:
    """Diagnose pack configuration issues.

    Returns a list of diagnostic dicts with keys:
    - level: "error" | "warning"
    - pack_name: str
    - issue: str
    - detail: str
    - action: str (suggested fix)
    """
    from loopforge.engine import repository_root as _repo_root

    if registry is None:
        registry = PackRegistry(
            project_dir,
            bundled_root=_repo_root(),
            bundled_packs_root=Path(__file__).resolve().parents[1] / "packs",
            store=DEFAULT_JSON_STORE,
            config_dir=".loopforge",
            default_pack="generic-code",
        )

    diagnostics: list[dict[str, str]] = []

    packs_root = project_dir / ".loopforge" / "packs"
    if not packs_root.exists():
        return diagnostics

    for pack_dir in sorted(packs_root.iterdir()):
        if not pack_dir.is_dir():
            continue
        pack_json = pack_dir / "pack.json"
        if not pack_json.exists():
            diagnostics.append({
                "level": "warning",
                "pack_name": pack_dir.name,
                "issue": "pack directory has no pack.json",
                "detail": f"Directory {pack_dir} exists but contains no pack.json",
                "action": f"Add a valid pack.json to {pack_dir} or remove the directory.",
            })
            continue

        try:
            data = registry.store.read_object(pack_json)
        except json.JSONDecodeError as exc:
            diagnostics.append({
                "level": "error",
                "pack_name": pack_dir.name,
                "issue": "pack.json is not valid JSON",
                "detail": str(exc),
                "action": f"Fix JSON syntax in {pack_json} or remove the pack directory.",
            })
            continue
        except OSError as exc:
            diagnostics.append({
                "level": "error",
                "pack_name": pack_dir.name,
                "issue": "pack.json could not be read",
                "detail": str(exc),
                "action": f"Check file permissions for {pack_json}.",
            })
            continue

        name = str(data.get("name") or pack_dir.name).strip()
        if not name:
            diagnostics.append({
                "level": "error",
                "pack_name": pack_dir.name,
                "issue": "pack.json is missing 'name' field",
                "detail": f"{pack_json} must define a non-empty 'name' field",
                "action": f"Add a 'name' field to {pack_json}.",
            })
            continue

        try:
            contract = registry._resolve_contract(name, ())
        except PackCycleError as exc:
            diagnostics.append({
                "level": "error",
                "pack_name": name,
                "issue": "cyclic pack inheritance",
                "detail": str(exc),
                "action": "Remove or rewire the extends chain to break the cycle.",
            })
            continue
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            diagnostics.append({
                "level": "error",
                "pack_name": name,
                "issue": "pack.json is malformed",
                "detail": str(exc),
                "action": f"Correct the validation error in {pack_json}.",
            })
            continue
        except Exception:
            continue

        for file_key, file_label in (
            ("agents_file", "agents"),
            ("permissions_file", "permissions"),
            ("workflow_file", "workflow"),
            ("checks_file", "checks"),
        ):
            file_path_str = contract.get(file_key)
            if isinstance(file_path_str, str) and file_path_str:
                file_path = Path(file_path_str)
                if not file_path.exists():
                    diagnostics.append({
                        "level": "warning",
                        "pack_name": name,
                        "issue": f"missing referenced {file_label} file",
                        "detail": f"Pack '{name}' references {file_label} at {file_path}, but the file does not exist",
                        "action": f"Create {file_path} or remove the reference in pack.json.",
                    })

    registry.discover_contracts(collect_diagnostics=True)
    diagnostics.extend(registry._last_discovery_diagnostics)

    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for diag in diagnostics:
        key = (diag["pack_name"], diag["issue"])
        if key not in seen:
            seen.add(key)
            unique.append(diag)
    return unique


class PackTrustStore:
    """Persistent store of approved pack hashes."""

    def __init__(self, store: JsonStore, home: Path):
        self._store = store
        self._path = home / "trusted_packs.json"

    def _read(self) -> dict[str, Any]:
        data, diagnostic = safe_read_json(self._store, self._path)
        if data is None:
            if diagnostic and "File not found" not in (diagnostic or ""):
                logger.error("Trust store corrupt: %s", diagnostic)
            return {"version": 1, "packs": {}}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._store.write_object(self._path, data)

    def is_trusted(self, pack_hash: str) -> bool:
        data = self._read()
        return pack_hash in data.get("packs", {})

    def trust(self, pack_hash: str, pack_name: str, commands: list[str]) -> None:
        data = self._read()
        data.setdefault("packs", {})[pack_hash] = {
            "name": pack_name,
            "commands": commands,
            "trusted_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write(data)

    def untrust(self, pack_hash: str) -> None:
        data = self._read()
        data.get("packs", {}).pop(pack_hash, None)
        self._write(data)

    def list_trusted(self) -> dict[str, dict[str, Any]]:
        return dict(self._read().get("packs", {}))


def pack_trust_store(home: Path | None = None) -> PackTrustStore:
    from loopforge.engine import loopforge_home

    return PackTrustStore(DEFAULT_JSON_STORE, loopforge_home(home=home))
