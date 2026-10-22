"""Selected Live composition: read-only documents and authoritative next action."""
from __future__ import annotations

import tempfile
import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from loopforge.cli.actions import ActionDescriptor
from loopforge.cli.models import OperationSnapshot
from loopforge.cli.run_context import RunContextSection, RunContextSnapshot
from loopforge.cli.run_evidences import load_run_evidences
from loopforge.cli.run_reading import RunReading
from loopforge.cli.textual_app import LoopForgeApp
from loopforge.cli.textual_app.run_presenter import execution_result
from tests.test_run_live_tui import synthetic_run


def ready_run(app):
    snapshot = synthetic_run(app)
    action = ActionDescriptor('verify', 'Generate the patch and run deterministic checks',
        'The current run is ready for verification.', 'verification', True, True,
        'loopforge verify', 'verify')
    run = replace(snapshot.run.shell.run, family='ready', status='verification_pending',
                  current_stage='verification', next_action=action)
    shell = replace(snapshot.run.shell, run=run, family='ready', state='verification_pending')
    agent = replace(snapshot.run.agent, stage_id='implementation', attempt_number=2,
        session_id='attempts/attempt-002', session_closed=True, result_ref='attempts/attempt-002/result.json')
    return replace(snapshot, operation=OperationSnapshot('empty'),
        run=replace(snapshot.run, shell=shell, agent=agent,
            attempts=({'number': 1, 'status': 'failed'}, {'number': 2, 'status': 'completed'}),
            sessions=({'stage_id': 'implementation', 'session_id': 'attempts/attempt-002', 'label': 'Attempt 02'},)))


class ResultProjectionTests(unittest.TestCase):
    def setUp(self):
        self.app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme='dark'), load_on_mount=False)
        self.snapshot = ready_run(self.app)

    def test_closed_session_and_agent_claim_are_not_success(self):
        run = replace(self.snapshot.run, attempts=(), agent=replace(self.snapshot.run.agent,
            implementation_contract='Agent says: verification passed', result_ref=''))
        result = execution_result(replace(self.snapshot, run=run))
        self.assertIn('session closed', result.plain)
        self.assertNotIn('Agent finished', result.plain)
        self.assertNotIn('passed', result.plain)
        self.assertIsNone(execution_result(self.snapshot, active=True))

    def test_verification_receipt_must_match_candidate_and_execution(self):
        run = replace(self.snapshot.run, candidate_revision=3,
                      verification={'candidate_revision': 2, 'status': 'passed'})
        result = execution_result(replace(self.snapshot, run=run)).plain
        self.assertIn('Outdated receipt', result)
        self.assertNotIn('passed', result)
        history = replace(run, agent=replace(run.agent, attempt_number=1,
                                            session_id='attempts/attempt-001'))
        result = execution_result(replace(self.snapshot, run=history)).plain
        self.assertNotIn('Verification', result)
        self.assertNotIn('Next', result)

    def test_counts_only_from_complete_execution_snapshot(self):
        from loopforge.cli.run_changes import RunChangesSnapshot, RunFileChange
        changes = RunChangesSnapshot(capture_state='complete', source='runner-workspace-snapshots',
            files=(RunFileChange('a.py', 'M', additions=2, deletions=1),))
        result = execution_result(replace(self.snapshot, run=replace(self.snapshot.run, changes=changes))).plain
        self.assertIn('+2 -1', result)
        stale = replace(changes, stale=True)
        result = execution_result(replace(self.snapshot, run=replace(self.snapshot.run, changes=stale))).plain
        self.assertNotIn('Changes', result)

    def test_unrelated_stage_does_not_inherit_current_next_action(self):
        agent = replace(self.snapshot.run.agent, stage_id='research', attempt_number=None,
                        session_id='artifacts/stages/research')
        run = replace(self.snapshot.run, agent=agent,
                      sessions=({'stage_id': 'research', 'session_id': agent.session_id},))
        self.assertNotIn('Next', execution_result(replace(self.snapshot, run=run)).plain)

    def test_ascii_receipt_uses_textual_status_and_separators(self):
        with patch.dict(os.environ, {'LOOPFORGE_ASCII': '1'}):
            text = execution_result(self.snapshot).plain
        self.assertTrue(text.startswith('+ Agent finished'))
        self.assertNotIn('·', text)


class EvidenceRecordTests(unittest.TestCase):
    def test_records_preview_only_confined_selected_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selected = root / 'attempts/attempt-002'
            selected.mkdir(parents=True)
            (selected / 'result.json').write_text('{"tests": "passed [red]"}')
            (selected / 'escape.json').symlink_to('/etc/passwd')
            other = root / 'attempts/attempt-001'
            other.mkdir()
            (other / 'result.json').write_text('historical')
            session = SimpleNamespace(session_id='attempts/attempt-002', session_dir='attempts/attempt-002',
                                      stage_id='implementation', attempt_number=2)
            status = SimpleNamespace(run_dir=root, run={'attempts': [{'number': 2}],
                                     'current_stage': 'implementation'}, blockers=())
            evidence = load_run_evidences(status, session)
            records = evidence.sections[0].records
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].language, 'json')
            self.assertIn('[red]', records[0].preview)
            self.assertNotIn('historical', records[0].preview)
            self.assertIn('not a verification receipt', records[0].body)


class SelectedCompositionPilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_on_run_controls_never_dispatches_next_stage(self):
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme='dark'), load_on_mount=False)
        async with app.run_test(size=(120, 32)) as pilot:
            app._screen = 'run'
            snapshot = ready_run(app)
            app._render_snapshot(snapshot)
            await pilot.pause()
            with patch.object(app, 'request_action') as request, patch.object(app, '_change_run_reading') as reading:
                app.query_one('#run-view-context').focus()
                await pilot.press('enter')
                reading.assert_called_once_with(view='Context')
                request.assert_not_called()
                reading.reset_mock()
                app.query_one('#run-mode-raw').focus()
                await pilot.press('enter')
                reading.assert_called_once_with(mode='Raw')
                request.assert_not_called()
                await pilot.press('ctrl+enter')
                request.assert_called_once_with(snapshot.run.shell.run.next_action)

    async def test_ready_action_dispatch_and_busy_or_unavailable_suppression(self):
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme='dark'), load_on_mount=False)
        async with app.run_test(size=(120, 30)) as pilot:
            app._screen = 'run'
            snapshot = ready_run(app)
            app._render_snapshot(snapshot)
            await pilot.pause()
            self.assertIn('Next step', str(app.query_one('#run-action-title').render()))
            self.assertFalse(app.query('#run-result-changes'))
            self.assertTrue(app.query_one('#run-required-action').display)
            with patch.object(app, 'request_action') as request:
                await pilot.press('ctrl+enter')
                request.assert_called_once_with(snapshot.run.shell.run.next_action)
                self.assertTrue(request.call_args.args[0].requires_confirmation)
            busy = replace(snapshot, operation=OperationSnapshot('loading'))
            app._render_snapshot(busy)
            await pilot.pause()
            self.assertFalse(app.query_one('#run-required-action').display)
            with patch.object(app, 'request_action') as request:
                await pilot.press('ctrl+enter')
                request.assert_not_called()
            app._refreshing_after_operation = True
            app._render_snapshot(snapshot)
            self.assertFalse(app.query_one('#run-required-action').display)
            app._refreshing_after_operation = False
            action = replace(snapshot.run.shell.run.next_action, available=False)
            shell = replace(snapshot.run.shell, run=replace(snapshot.run.shell.run, next_action=action))
            app._render_snapshot(replace(snapshot, run=replace(snapshot.run, shell=shell)))
            self.assertFalse(app.query_one('#run-required-action').display)
            with patch.object(app, 'request_action') as request:
                app.action_run_required_action()
                request.assert_not_called()

    async def test_document_selection_raw_focus_and_scope_are_read_only(self):
        from loopforge.cli.textual_app.widgets import RunDocumentView
        from textual.widgets import OptionList
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme='dark'), load_on_mount=False)
        async with app.run_test(size=(120, 32)) as pilot:
            app._screen = 'run'
            snapshot = ready_run(app)
            context = RunContextSnapshot(sections=(RunContextSection('mission','Mission','# Goal\nFix **tests**', expanded=True),),
                                         raw_prompt='# Original\n[red] literal', capture_state='complete')
            snapshot = replace(snapshot, run=replace(snapshot.run, reading=RunReading(view='Context'), context=context))
            app._render_snapshot(snapshot)
            await pilot.pause()
            view = app.query_one(RunDocumentView)
            navigator = view.query_one(OptionList)
            navigator.focus()
            with patch.object(app, 'request_action') as request:
                await pilot.press('down', 'enter')
                await pilot.pause()
                self.assertEqual(view._selected_key, 'raw')
                self.assertEqual(view._items['raw'].detail.render().plain.splitlines()[-1], '[red] literal')
                await pilot.press('enter')
                request.assert_not_called()
            selected = view._items['raw']
            app._render_snapshot(snapshot)
            await pilot.pause()
            self.assertIs(view._items['raw'], selected)
            self.assertEqual(view._selected_key, 'raw')
            for width in (60,80,160):
                await pilot.resize_terminal(width,24)
                await pilot.pause()
                self.assertGreater(view.query_one('#run-document-index').size.width, 0)
                self.assertGreater(view.query_one('#run-document-preview').size.width, 0)
                self.assertLessEqual(app.query_one('#run-command-bar').region.bottom, app.size.height)
            self.assertEqual(view._selected_key, 'raw')
            view.update_sections(('different-run','Context'), (('other','Other','Other run instructions',True),))
            await pilot.pause()
            self.assertNotIn('raw', view._items)

    async def test_approval_color_titles_and_existing_command_preserved(self):
        app = LoopForgeApp(SimpleNamespace(project_dir=Path.cwd(), theme='dark'), load_on_mount=False)
        async with app.run_test(size=(80,24)) as pilot:
            app._screen='run'
            snapshot=ready_run(app)
            shell=replace(snapshot.run.shell,family='needs_human',run=replace(snapshot.run.shell.run,family='needs_human'))
            app._render_snapshot(replace(snapshot,run=replace(snapshot.run,shell=shell)))
            await pilot.pause()
            self.assertIn('Approval required',str(app.query_one('#run-action-title').render()))
            self.assertEqual(app.query_one('#run-action-title').styles.color.hex,'#FFB869')
            command=app.query_one('#run-command-bar')
            self.assertEqual(command.styles.height.value,4)
            self.assertEqual(str(command.border_title),'Command Input')
            for selector in ('configuration','steps','metrics'):
                title=str(app.query_one('#run-context-'+selector+'-panel').border_title)
                self.assertEqual(title,title.upper())
            self.assertGreaterEqual(command.region.y,app.query_one('#run-required-action').region.bottom)
            self.assertGreaterEqual(app.query_one('#run-activity-feed').size.height,4)
