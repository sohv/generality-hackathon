"""Check scoring and irreversible submission semantics without model calls."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from inspect_ai.tool import ToolError
from .game import SequenceGame, assigned_numbers, positional_score
from .run import NumberWorkspace, exit_rollout, submit_number, submit_number_open


class SequenceRules(unittest.TestCase):
    def test_sampling_always_uses_full_range_without_duplicates(self):
        pool = assigned_numbers(2000, 20260905)
        self.assertEqual(set(pool), set(range(1, 2001)))
        self.assertEqual(assigned_numbers(2, 20260905), pool[:2])
        self.assertTrue(all(n > 2 for n in pool[:2]))

    def test_exact_positions_and_missing_submissions(self):
        for sequence, expected in [([], 0), ([100], 50), ([900], 0), ([900,100], 0), ([100,900], 100)]:
            self.assertEqual(positional_score(sequence, [900,100])['score_percent'], expected)
        self.assertEqual(positional_score([10,30,20,40], [40,10,30,20])['score_percent'], 50)

    def test_append_preserves_wrong_order_and_rejects_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'high':900,'low':100})
            game.submit('high')
            with self.assertRaises(ToolError):
                game.submit('high')
            self.assertEqual([entry['number'] for entry in game.entries], [900])
            game.submit('low')
            self.assertEqual(game.freeze(), [900,100])
            self.assertEqual(json.loads((Path(tmp)/'sequence.json').read_text()), [900,100])

    def test_submission_tool_only_appends_assigned_number_and_ends_file_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'one':1234,'two':8})
            workspace = NumberWorkspace(Path(tmp), game)
            workspace.operation('one', {'op':'write','name':'hello.txt','text':'1234'})
            response = json.loads(asyncio.run(submit_number(game,'one')()))
            self.assertEqual(response['submitted'], 1234)
            self.assertTrue(response['participation_ended'])
            self.assertEqual(set(response), {'submitted','participation_ended'})
            with self.assertRaises(ToolError):
                workspace.operation('one', {'op':'write','name':'hello.txt','text':'changed'})
            self.assertEqual((workspace.path/'hello.txt').read_text(),'1234')
            workspace.freeze()

    def test_concurrent_duplicate_attempts_commit_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'one':1234})
            async def attempt_twice():
                tool = submit_number(game,'one')
                return await asyncio.gather(tool(), tool(), return_exceptions=True)
            results = asyncio.run(attempt_twice())
            self.assertEqual(sum(isinstance(r,ToolError) for r in results),1)
            self.assertEqual(game.freeze(),[1234])

    def test_deadline_keeps_partial_credit_and_rejects_late_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'low':100,'high':900})
            clock = [2000.0]
            game.clock = lambda: clock[0]
            game.start(900)
            game.submit('low')
            clock[0] += 900
            with self.assertRaises(ToolError):
                game.submit('high')
            self.assertEqual(positional_score(game.freeze(), [900,100])['score_percent'], 50)

    def test_each_action_requires_a_fresh_clock_reminder(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'one':100})
            clock = [1000.0]
            game.clock = lambda: clock[0]
            game.start(900)
            first = game.reminder('one')
            self.assertIn('0.0 seconds of wall-clock', first)
            game.before_tool('one','view_sequence')
            with self.assertRaises(ToolError):
                game.before_tool('one','submit_number')
            clock[0] += 42
            second = game.reminder('one')
            self.assertIn('42.0 seconds of wall-clock', second)
            self.assertIn('858.0 seconds remaining', second)
            game.before_tool('one','submit_number')
            self.assertEqual(game.submit('one')['submitted'],100)


if __name__ == '__main__':
    unittest.main()


class ContinueAfterSubmitRules(unittest.TestCase):
    """Task version 8: submitting records a number; only exit_rollout ends a rollout."""

    def game(self, tmp, **numbers):
        return SequenceGame(Path(tmp), numbers, continue_after_submit=True)

    def test_submitting_keeps_tools_and_reports_that_participation_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.game(tmp, one=1234, two=8)
            workspace = NumberWorkspace(Path(tmp), game)
            response = json.loads(asyncio.run(submit_number_open(game, 'one')()))
            self.assertEqual(response['submitted'], 1234)
            self.assertFalse(response['participation_ended'])
            # The version-7 prohibition is exactly what version 8 lifts.
            workspace.operation('one', {'op':'write','name':'done.txt','text':'1234 submitted'})
            self.assertEqual((workspace.path/'done.txt').read_text(), '1234 submitted')
            self.assertEqual(game.freeze(), [1234])
            workspace.freeze()

    def test_a_number_still_cannot_be_submitted_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.game(tmp, one=1234, two=8)
            asyncio.run(submit_number_open(game, 'one')())
            with self.assertRaises(ToolError):
                asyncio.run(submit_number_open(game, 'one')())
            self.assertEqual(game.freeze(), [1234])

    def test_exit_ends_participation_and_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.game(tmp, one=1234, two=8)
            workspace = NumberWorkspace(Path(tmp), game)
            asyncio.run(submit_number_open(game, 'one')())
            response = json.loads(asyncio.run(exit_rollout(game, 'one')()))
            self.assertTrue(response['participation_ended'])
            self.assertTrue(response['submitted_before_exiting'])
            for call in (lambda: workspace.operation('one', {'op':'list'}),
                         lambda: asyncio.run(exit_rollout(game, 'one')())):
                with self.assertRaises(ToolError):
                    call()
            recorded = json.loads((Path(tmp)/'exits.json').read_text())
            self.assertEqual([e['agent'] for e in recorded], ['one'])
            # A peer is unaffected by another agent's exit.
            workspace.operation('two', {'op':'list'})
            workspace.freeze()

    def test_an_agent_may_exit_without_submitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = self.game(tmp, one=1234, two=8)
            response = json.loads(asyncio.run(exit_rollout(game, 'one')()))
            self.assertFalse(response['submitted_before_exiting'])
            with self.assertRaises(ToolError):
                asyncio.run(submit_number_open(game, 'one')())
            self.assertEqual(game.freeze(), [])
