from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_engine() -> None:
    path = ROOT / "src" / "loopforge" / "engine" / "__init__.py"

    replace_once(
        path,
        """    is_kilo_run_command,\n)\nfrom loopforge.engine.packs import PackRegistry\n""",
        """    is_kilo_run_command,\n)\nfrom loopforge.checks import validate_implementation_result\nfrom loopforge.engine.packs import PackRegistry\n""",
    )

    replace_once(
        path,
        '''def expected_session_for(run: dict[str, Any], adapter: str, workspace_dir: Path) -> dict[str, Any]:
    seed = {
        "base_commit": run.get("base_commit"),
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "adapter": adapter,
        "workspace": str(workspace_dir.resolve()),
    }
    return {
        "risk": "low",
        "base_commit": run.get("base_commit"),
        "workspace": str(workspace_dir.resolve()),
        "runner_id": adapter,
        "preflight_sha256": session_hash(seed, "preflight"),
        "start_authorization_receipt_sha256": session_hash(seed, "start-authorization"),
    }
''',
        '''def run_issue_number(run: dict[str, Any]) -> int:
    direct = run.get("issue")
    if isinstance(direct, int) and not isinstance(direct, bool) and direct >= 1:
        return direct

    evidence = run.get("evidence", {})
    source = evidence.get("source", {}) if isinstance(evidence, dict) else {}
    if isinstance(source, dict):
        for key in ("issue", "number", "issue_number"):
            value = source.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
                return value
        for key in ("reference", "url"):
            value = source.get(key)
            if not isinstance(value, str):
                continue
            match = re.search(r"(?:#|/issues/)([1-9][0-9]*)(?:\\D|$)", value)
            if match:
                return int(match.group(1))

    # Native tasks do not always originate from an issue, while the portable
    # implementation-result contract requires a positive issue identifier.
    return 1


def expected_session_for(run: dict[str, Any], adapter: str, workspace_dir: Path) -> dict[str, Any]:
    issue = run_issue_number(run)
    seed = {
        "issue": issue,
        "base_commit": run.get("base_commit"),
        "run_id": run.get("run_id"),
        "task_id": run.get("task_id"),
        "adapter": adapter,
        "workspace": str(workspace_dir.resolve()),
    }
    session = {
        "issue": issue,
        "risk": "low",
        "base_commit": run.get("base_commit"),
        "workspace": str(workspace_dir.resolve()),
        "runner_id": adapter,
        "preflight_sha256": session_hash(seed, "preflight"),
        "start_authorization_receipt_sha256": session_hash(seed, "start-authorization"),
    }
    return validate_implementation_result.validate_expected_session(session)


def validate_attempt_result(
    result: dict[str, Any],
    session: dict[str, Any],
) -> dict[str, Any]:
    expected_session = validate_implementation_result.validate_expected_session(session)
    validated = validate_implementation_result.validate_result(result)
    mismatched = sorted(
        key for key, value in expected_session.items() if validated.get(key) != value
    )
    if mismatched:
        raise ValueError(
            "Implementation result session mismatch: " + ", ".join(mismatched)
        )
    return validated
''',
    )

    replace_once(
        path,
        '''    profile_stop_reasons: list[str] = []
    if normalize_profile(run.get("profile")) == "autonomous":
        profile_stop_reasons = adapter_result_stop_reasons(result)
        if profile_stop_reasons and status == "completed":
            status = "blocked"
            result["status"] = status
            result["summary"] = (
                str(result.get("summary", "")).rstrip()
                + " Autonomy profile stopped for human review."
            ).strip()

    stdout_path = attempt_dir / "adapter.stdout"
''',
        '''    profile_stop_reasons: list[str] = []
    if normalize_profile(run.get("profile")) == "autonomous":
        profile_stop_reasons = adapter_result_stop_reasons(result)
        if profile_stop_reasons and status == "completed":
            status = "blocked"
            result["status"] = status
            result["next_action"] = "human_review"
            result["summary"] = (
                str(result.get("summary", "")).rstrip()
                + " Autonomy profile stopped for human review."
            ).strip()

    contract_validation_error = ""
    invalid_result_path: Path | None = None
    try:
        result = validate_attempt_result(result, session)
        status = str(result["status"])
    except ValueError as error:
        contract_validation_error = str(error)
        invalid_result_path = attempt_dir / "result.invalid.json"
        write_json_atomic(invalid_result_path, result)
        status = "failed"
        result = synthetic_adapter_result(
            session=session,
            status=status,
            summary=(
                f"Implementation result contract validation failed: {error}"
            )[:1000],
            workspace_changed=snapshot_changed,
        )
        result = validate_attempt_result(result, session)

    stdout_path = attempt_dir / "adapter.stdout"
''',
    )

    replace_once(
        path,
        '''        "profile_stop_reasons": profile_stop_reasons,
        "publication_requested": bool(result.get("publication_requested", False)),
''',
        '''        "profile_stop_reasons": profile_stop_reasons,
        "contract_validation_error": contract_validation_error or None,
        "invalid_result_path": (
            relative_to_run(run_dir, invalid_result_path)
            if invalid_result_path is not None
            else None
        ),
        "publication_requested": bool(result.get("publication_requested", False)),
''',
    )


def patch_github_metadata() -> None:
    path = ROOT / "src" / "loopforge" / "cli" / "github.py"
    replace_once(
        path,
        '''        return {
            "type": "github_issue",
            "provider": "github",
            "reference": f"{ref.owner}/{ref.repo}#{ref.number}",
''',
        '''        return {
            "type": "github_issue",
            "provider": "github",
            "issue": ref.number,
            "reference": f"{ref.owner}/{ref.repo}#{ref.number}",
''',
    )


def main() -> None:
    patch_engine()
    patch_github_metadata()


if __name__ == "__main__":
    main()
