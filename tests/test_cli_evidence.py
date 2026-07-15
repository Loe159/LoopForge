from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from loopforge.cli.evidence import approval_summary, evidence_items, preview_evidence
from loopforge.cli.tui import LoopForgeConsole


class EvidenceViewerTests(unittest.TestCase):
    def test_indexes_searches_and_previews_real_run_artifacts(self) -> None:
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "artifacts" / "attempts").mkdir(parents=True)
            (run_dir / "artifacts" / "memory").mkdir()
            (run_dir / "plan.md").write_text("# Plan\n\n1. Update the widget\n", encoding="utf-8")
            (run_dir / "review.md").write_text("# Review\n\n## Findings\n- none\n", encoding="utf-8")
            (run_dir / "artifacts" / "checks.md").write_text("tests passed", encoding="utf-8")
            (run_dir / "artifacts" / "patch.diff").write_text("+ widget\n", encoding="utf-8")
            (run_dir / "artifacts" / "attempts" / "stderr.txt").write_text("adapter stopped", encoding="utf-8")
            (run_dir / "artifacts" / "memory" / "proposals.md").write_text("remember widget", encoding="utf-8")

            items = evidence_items(run_dir)
            kinds = {item.relative_path: item.kind for item in items}
            self.assertEqual(kinds["plan.md"], "plan")
            self.assertEqual(kinds["review.md"], "review")
            self.assertEqual(kinds["artifacts/checks.md"], "check")
            self.assertEqual(kinds["artifacts/patch.diff"], "diff")
            self.assertEqual(kinds["artifacts/attempts/stderr.txt"], "log")
            self.assertEqual(kinds["artifacts/memory/proposals.md"], "memory")

            matches = evidence_items(run_dir, query="stopped")
            self.assertEqual([item.relative_path for item in matches], ["artifacts/attempts/stderr.txt"])
            self.assertEqual(preview_evidence(matches[0], query="stopped"), "adapter stopped")

    def test_approval_summary_uses_recorded_plan_and_review_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "plan.md").write_text(
                "# Plan\n\n## Implementation\n1. Change one\n2. Change two\n\n## Files\n- src/widget.py\n",
                encoding="utf-8",
            )
            (run_dir / "review.md").write_text(
                "# Review\n\n## Findings\n- Correctness checked\n- Tests covered\n",
                encoding="utf-8",
            )
            run = {
                "loop_contract": {"success_checks": ["tests pass", "format passes"]},
                "verification": {"status": "passed", "risk": {"risk": "low"}},
            }

            plan = approval_summary(run_dir, run, "plan")
            review = approval_summary(run_dir, run, "review")

            self.assertEqual(plan.title, "Approve implementation plan?")
            self.assertIn("2 planned steps recorded.", plan.lines)
            self.assertIn("1 file in recorded scope.", plan.lines)
            self.assertIn("2 success checks required before review.", plan.lines)
            self.assertIn("Verification: passed.", review.lines)
            self.assertIn("2 review findings recorded.", review.lines)
            self.assertIn("Recorded risk: low.", review.lines)

    def test_console_opens_searches_and_exports_selected_evidence(self) -> None:
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            source = run_dir / "artifacts" / "attempts" / "stderr.txt"
            source.parent.mkdir(parents=True)
            source.write_text("adapter blocked by a check", encoding="utf-8")
            shell = SimpleNamespace(project_dir=run_dir, copy_to_clipboard=lambda text: False)
            console = LoopForgeConsole(shell)
            console.state.screen = "evidence"
            console.state.evidence_query = "blocked"
            status = SimpleNamespace(run_dir=run_dir, run={})

            console._statuses[run_dir.resolve()] = status
            console._load_evidence_snapshot(run_dir)
            fragments = console._evidence_fragments()
            self.assertIn("stderr.txt", "".join(text for _, text in fragments))
            console._open_selected_evidence()
            self.assertTrue(console.state.evidence_preview)
            exported = console._export_evidence_item(console._selected_evidence_item())

            self.assertEqual(exported, Path("artifacts/exports/stderr-evidence.txt"))
            self.assertEqual(
                (run_dir / exported).read_text(encoding="utf-8"),
                "adapter blocked by a check",
            )


if __name__ == "__main__":
    unittest.main()
