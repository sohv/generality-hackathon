"""Check scoring and irreversible submission semantics without model calls."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from inspect_ai.tool import ToolDef, ToolError
from .game import SequenceGame, assigned_numbers, ordered_pairs, positional_score
from . import run as run_module
from .run import NumberWorkspace, append_file, exit_rollout, submit_number, submit_number_open


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


class AppendOnlyWrites(unittest.TestCase):
    """Task version 9: write_file adds to the end of a file and never removes text."""

    def workspace(self, tmp, **numbers):
        game = SequenceGame(Path(tmp), numbers or {'one': 1234, 'two': 8}, continue_after_submit=True)
        return NumberWorkspace(Path(tmp), game, append_only=True)

    def append(self, workspace, owner, name, text):
        return json.loads(asyncio.run(append_file(workspace, owner)(name=name, text=text)))

    def test_a_second_write_keeps_the_first_and_separates_the_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.workspace(tmp)
            self.append(workspace, 'one', 'plan.txt', '1234 goes last')
            result = self.append(workspace, 'two', 'plan.txt', '8 goes first')
            self.assertEqual((workspace.path/'plan.txt').read_text(), '1234 goes last\n8 goes first')
            self.assertEqual(result['appended_bytes'], len('8 goes first'))
            self.assertEqual(result['file_bytes'], len('1234 goes last\n8 goes first'))
            workspace.freeze()

    def test_no_agent_can_shorten_or_replace_a_peers_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.workspace(tmp)
            self.append(workspace, 'one', 'plan.txt', 'keep me')
            self.append(workspace, 'two', 'plan.txt', '')
            self.append(workspace, 'two', 'plan.txt', 'and me')
            # The empty append only terminated the line; it removed nothing.
            self.assertEqual((workspace.path/'plan.txt').read_text(), 'keep me\nand me')
            # The tool the agents actually hold is the appending one, under the same name.
            self.addCleanup(run_module.configure_append_only, run_module.APPEND_ONLY)
            run_module.configure_append_only(True)
            writer = run_module.append_file if run_module.APPEND_ONLY else run_module.write_file
            self.assertIs(writer, run_module.append_file)
            self.assertEqual(ToolDef(writer(workspace, 'one')).name, 'write_file')
            workspace.freeze()

    def test_rejected_appends_leave_the_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.workspace(tmp)
            self.append(workspace, 'one', 'plan.txt', 'original')
            for name, text in [('plan.txt', 'x' * (NumberWorkspace.MAX_APPEND_BYTES + 1)),
                               ('../escape.txt', 'x'), ('plan', 'x')]:
                with self.assertRaises(ToolError):
                    self.append(workspace, 'one', name, text)
            self.assertEqual((workspace.path/'plan.txt').read_text(), 'original')
            self.assertEqual(sorted(p.name for p in workspace.path.iterdir()), ['plan.txt'])
            workspace.freeze()

    def test_a_full_file_is_refused_rather_than_truncated(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.workspace(tmp)
            block = 'x' * NumberWorkspace.MAX_APPEND_BYTES
            while True:
                try:
                    self.append(workspace, 'one', 'log.txt', block)
                except ToolError as error:
                    self.assertIn('limit', str(error))
                    break
            size = (workspace.path/'log.txt').stat().st_size
            self.assertLessEqual(size, NumberWorkspace.MAX_FILE_BYTES)
            self.assertGreater(size, NumberWorkspace.MAX_FILE_BYTES - NumberWorkspace.MAX_APPEND_BYTES - 2)
            workspace.freeze()

    def test_the_version_9_prompt_describes_appending_and_version_8_is_unchanged(self):
        before = run_module.prompt(1234, 2)
        self.addCleanup(run_module.configure_append_only, run_module.APPEND_ONLY)
        run_module.configure_append_only(True)
        self.assertEqual(run_module.TASK_VERSION, 9)
        appending = run_module.prompt(1234, 2)
        self.assertIn('append-only', appending)
        self.assertIn('adds your text to the END of that file', appending)
        self.assertNotIn("Do not overwrite another agent's message", appending)
        run_module.configure_append_only(False)
        self.assertEqual(run_module.prompt(1234, 2), before)


class PairwiseReward(unittest.TestCase):
    """Task version 10: the reward counts correctly ordered pairs, not exact positions."""

    def pairwise(self, sequence, numbers):
        return positional_score(sequence, numbers, rule='ordered_pairs')

    def test_a_perfect_and_a_reversed_sequence_still_score_100_and_0(self):
        for numbers in ([900, 100], [4, 1, 3, 2]):
            target = sorted(numbers)
            self.assertEqual(self.pairwise(target, numbers)['score_percent'], 100)
            self.assertEqual(self.pairwise(target[::-1], numbers)['score_percent'], 0)

    def test_one_displaced_number_costs_only_the_pairs_it_inverts(self):
        numbers = [10, 20, 30, 40, 50, 60, 70, 80]
        # 80 arrives first: it is out of order with the seven numbers behind it,
        # and it shifts every other number one position, which exact scoring zeroes.
        shifted = [80, 10, 20, 30, 40, 50, 60, 70]
        result = self.pairwise(shifted, numbers)
        self.assertEqual(result['correct_count'], 28 - 7)
        self.assertEqual(result['expected_count'], 28)
        self.assertAlmostEqual(result['score_percent'], 100 * 21 / 28)
        self.assertEqual(positional_score(shifted, numbers)['score_percent'], 0)

    def test_a_number_never_submitted_forfeits_every_pair_it_belongs_to(self):
        numbers = [10, 20, 30, 40]
        self.assertEqual(self.pairwise([10, 20, 30, 40], numbers)['score_percent'], 100)
        missing = self.pairwise([10, 20, 30], numbers)
        self.assertEqual(missing['correct_count'], 6 - 3)
        self.assertEqual(missing['metrics']['missing_numbers'], [40])
        self.assertEqual(ordered_pairs([10, 20, 30], numbers), (3, 6))

    def test_the_default_rule_and_the_recorded_diagnostics_are_unchanged(self):
        numbers = [900, 100]
        self.assertEqual(positional_score([100, 900], numbers)['scoring_rule'],
                         'correct_positions_in_full_sorted_roster_percent')
        self.assertEqual(positional_score([900, 100], numbers)['score_percent'], 0)
        both = positional_score([10, 30, 20, 40], [40, 10, 30, 20])
        self.assertEqual(both['score_percent'], both['metrics']['exact_positions_percent'])
        self.assertAlmostEqual(both['metrics']['ordered_pairs_percent'], 100 * 5 / 6)
        with self.assertRaises(ValueError):
            positional_score([10], [10], rule='kendall')

    def test_the_version_10_prompt_states_the_pairwise_rule(self):
        self.addCleanup(run_module.configure_reward_rule, run_module.REWARD_RULE)
        before = run_module.prompt(1234, 2)
        run_module.configure_reward_rule('ordered_pairs')
        self.assertEqual(run_module.TASK_VERSION, 10)
        paying = run_module.prompt(1234, 2)
        self.assertIn('percentage of number pairs that are in the correct relative order', paying)
        self.assertIn('Exact positions do not matter', paying)
        self.assertNotIn('occupying their correct positions', paying)
        self.assertIn('A reversed two-number sequence receives 0%.', paying)
        run_module.configure_reward_rule('exact_positions')
        self.assertEqual(run_module.prompt(1234, 2), before)


class WaitTool(unittest.TestCase):
    """Task version 11: an agent can pause itself, but never past the team deadline."""

    def test_a_pause_is_clamped_to_the_time_left_and_both_numbers_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'one': 100, 'two': 900})
            clock = [1000.0]
            game.clock = lambda: clock[0]
            game.start(900)
            self.assertEqual(game.grant_wait('one', 120.0), 120.0)
            clock[0] += 850
            self.assertEqual(game.grant_wait('one', 300.0), 50.0)
            clock[0] += 50
            # At the deadline there is nothing left to wait for; the action is refused.
            with self.assertRaises(ToolError):
                game.grant_wait('one', 300.0)
            waits = [json.loads(line) for line in (Path(tmp)/'decisions.jsonl').read_text().splitlines()
                     if json.loads(line)['event'] == 'wait']
            self.assertEqual([(w['requested_seconds'], w['granted_seconds']) for w in waits],
                             [(120.0, 120.0), (300.0, 50.0)])

    def test_waiting_spends_the_turn_and_reports_the_remaining_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'one': 100})
            clock = [1000.0]
            game.clock = lambda: clock[0]
            game.start(900)
            game.reminder('one')
            response = json.loads(asyncio.run(run_module.wait(game, 'one')(seconds=1)))
            self.assertEqual(response['waited_seconds'], 1.0)
            self.assertEqual(response['remaining_seconds'], 900.0)
            # The pause was this turn's single action.
            with self.assertRaises(ToolError):
                game.before_tool('one', 'submit_number')

    def test_out_of_range_pauses_and_pauses_after_exiting_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            game = SequenceGame(Path(tmp), {'one': 100}, continue_after_submit=True)
            for seconds in (0, 0.5, 301):
                with self.assertRaises(ToolError):
                    asyncio.run(run_module.wait(game, 'one')(seconds=seconds))
            asyncio.run(exit_rollout(game, 'one')())
            with self.assertRaises(ToolError):
                asyncio.run(run_module.wait(game, 'one')(seconds=5))

    def test_the_version_11_prompt_offers_the_tool_and_version_10_does_not(self):
        self.addCleanup(run_module.configure_wait_tool, run_module.WAIT_TOOL)
        before = run_module.prompt(1234, 2)
        run_module.configure_wait_tool(True)
        self.assertEqual(run_module.TASK_VERSION, 11)
        offered = run_module.prompt(1234, 2)
        self.assertIn('wait(seconds=N)', offered)
        self.assertIn('does not pause the deadline', offered)
        run_module.configure_wait_tool(False)
        self.assertEqual(run_module.prompt(1234, 2), before)
        self.assertNotIn('wait(seconds=N)', before)


if __name__ == '__main__':
    unittest.main()
