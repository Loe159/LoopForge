"""Tests for engine facade stability.

Covers Subtask 6: all public symbols previously available on
loopforge.engine must still be accessible after the extraction.
"""

from __future__ import annotations

import unittest
import loopforge.engine


# Whitelist of symbols that MUST be accessible on the loopforge.engine facade.
# These are the public API that CLI handlers, interactive shell, and TUI depend on.
REQUIRED_PUBLIC_SYMBOLS = [
    # Constants
    "CONFIG_DIR", "CONFIG_FILE", "DEFAULT_PROFILE", "DEFAULT_PACK", "DEFAULT_ADAPTER",
    "SUPPORTED_ADAPTERS", "SUPPORTED_PROFILES", "WORKFLOW_STAGES",
    "READY_FOR_VERIFICATION", "VERIFIED", "VERIFICATION_FAILED", "ADAPTER_BLOCKED",
    # Dataclasses
    "InitResult", "RunResult", "StatusResult", "ContinueResult", "StageResult",
    "VerifyResult", "LearnResult", "MetricsRecordResult", "MetricsSummaryResult",
    "DashboardResult", "RunListResult", "ProjectListResult", "GlobalRunListResult",
    "OpenProjectResult", "ResumeRunResult", "CompactContextResult", "ConfigUpdateResult",
    "InstallationResult", "GuidedAction", "GuidanceResult", "ActionScope",
    "IndexRepairResult",
    # Core operations
    "initialize_project", "open_project", "create_run", "resume_run",
    "continue_run", "verify_run", "learn_run", "current_status", "current_guidance",
    "dashboard_snapshot", "list_runs", "list_runs_all_projects", "list_registered_projects",
    "approve_plan", "approve_review", "approve_initial_task", "complete_task_definition",
    "execute_readonly_stage", "next_readonly_stage", "prepare_draft_publication",
    "normalize_run_workflow_state", "initial_workflow_state",
    "archive_run", "archive_current_run", "set_default_adapter",
    "compact_current_context", "diagnose_pack_issues", "run_doctor",
    "rebuild_indexes", "index_diagnostics",
    # Models
    "EffectivePackContract", "PackRegistry",
    # Utilities
    "loopforge_home", "project_config_path", "normalize_config", "normalize_profile",
    "read_json", "write_json_atomic", "utc_now",
    "install_loopforge", "detect_project_pack", "load_pack_contract", "load_pack_checks",
    "discover_pack_contracts",
]


class EngineFacadeTests(unittest.TestCase):

    def test_all_required_symbols_present(self):
        missing = []
        for symbol in REQUIRED_PUBLIC_SYMBOLS:
            if not hasattr(loopforge.engine, symbol):
                missing.append(symbol)
        self.assertFalse(
            missing,
            f"Missing public symbols on loopforge.engine facade: {missing}"
        )

    def test_facade_is_importable(self):
        self.assertIsNotNone(loopforge.engine)

    def test_action_scope_has_to_dict_from_dict(self):
        scope_cls = loopforge.engine.ActionScope
        self.assertTrue(hasattr(scope_cls, 'to_dict'))
        self.assertTrue(hasattr(scope_cls, 'from_dict'))


if __name__ == "__main__":
    unittest.main()
