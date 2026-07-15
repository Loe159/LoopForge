from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from loopforge.cli.evidence import EvidenceIndex, approval_summary, evidence_items, preview_evidence
from unittest.mock import patch


class EvidenceViewerTests(unittest.TestCase):
    def test_index_keeps_metadata_separate_from_content(self) -> None:
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            artifact = run_dir / "artifacts" / "large.log"
            artifact.parent.mkdir()
            artifact.write_text("first line\n" + ("x" * 100_000), encoding="utf-8")

            with patch.object(Path, "read_text", side_effect=AssertionError("index must not read content")):
                index = EvidenceIndex.build(run_dir)

            item = index.items[0]
            self.assertEqual(item.relative_path, "artifacts/large.log")
            self.assertEqual(item.size, artifact.stat().st_size)
            self.assertGreater(item.mtime_ns, 0)
            self.assertLessEqual(len(index.preview(item)), 12_050)

    def test_preview_cache_and_incremental_invalidation(self) -> None:
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            artifact = run_dir / "attempt.log"
            artifact.write_text("before", encoding="utf-8")
            index = EvidenceIndex.build(run_dir)
            item = index.items[0]
            self.assertEqual(index.preview(item), "before")

            artifact.write_text("after changed", encoding="utf-8")
            self.assertEqual(index.preview(item), "before")
            self.assertTrue(index.invalidate("attempt.log"))
            self.assertEqual(index.preview(index.items[0]), "after changed")

    def test_preview_uses_independent_bounded_line_windows(self) -> None:
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            artifact = run_dir / "attempt.log"
            artifact.write_text("\n".join(f"line {number}" for number in range(500)), encoding="utf-8")
            index = EvidenceIndex.build(run_dir)
            item = index.items[0]

            first = index.preview(item)
            later = index.preview(item, line_start=240)

            self.assertIn("line 0", first)
            self.assertIn("line 240", later)
            self.assertNotIn("line 0\n", later)

    def test_search_batches_read_content_only_when_requested(self) -> None:
        with TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "first.log").write_text("ordinary output", encoding="utf-8")
            (run_dir / "second.log").write_text("contains needle", encoding="utf-8")
            index = EvidenceIndex.build(run_dir)

            batches = list(index.search_batches("needle", batch_size=1))

            self.assertTrue(batches)
            self.assertEqual([item.relative_path for item in batches[-1]], ["second.log"])

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

if __name__ == "__main__":
    unittest.main()
