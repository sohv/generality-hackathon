"""Exercise the actual Inspect ReAct callback with a local mock model."""
import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import ToolCall

from .game import SequenceGame
from .run import NumberWorkspace, LIMITS, number_team, sequence_score, prompt, timed_react


class PressureHistory(unittest.TestCase):
    def test_stalled_agent_stops_at_common_deadline_without_erasing_partial_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory/'agents').mkdir()
            assignments = {'low':100,'high':900}
            game = SequenceGame(directory, assignments)
            workspace = NumberWorkspace(directory, game)
            workspace.create = lambda: None

            async def respond(messages, tools, tool_choice, config):
                if 'number is 900.' in messages[0].text:
                    await asyncio.sleep(10)
                output = ModelOutput.from_content('mockllm','')
                output.message.tool_calls = [ToolCall(id='submit-low',function='submit_number',arguments={})]
                return output

            task = Task(dataset=[Sample(input='test')],solver=number_team(workspace,game,directory,assignments),
                        scorer=sequence_score(workspace,game,directory,list(assignments.values())),time_limit=15)
            with patch.dict(LIMITS, seconds_per_agent=.2):
                logs=eval(task,model=get_model('mockllm/model',custom_outputs=respond),
                          log_dir=str(directory/'logs'),display='none')
            sample=logs[0].samples[0]
            self.assertIsNone(sample.error)
            self.assertEqual(sample.scores['sequence_score'].value,50)
            self.assertEqual(game.freeze(),[100])
            self.assertTrue(sample.metadata['deadline_reached'])
            # Inspect reports 'Time limit exceeded...'; the harness's own team deadline
            # reports 'time limit: common ...'. Either satisfies this assertion.
            self.assertIn('time limit',sample.metadata['agents']['high']['limit'].lower())

    def test_reminders_before_decisions_and_one_action_per_reminder(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            game = SequenceGame(directory, {'one':100})
            clock = [1000.0]
            game.clock = lambda: clock[0]
            game.start(900)
            workspace = NumberWorkspace(directory, game)
            calls = []

            def respond(messages, tools, tool_choice, config):
                self.assertEqual({t.name for t in tools}, {'list_files','read_file','write_file','submit_number'})
                calls.append([m.model_dump(mode='json') for m in messages])
                output = ModelOutput.from_content('mockllm', '')
                if len(calls) == 1:
                    clock[0] += 42
                    output.message.tool_calls = [
                        ToolCall(id='read1', function='list_files', arguments={}),
                        ToolCall(id='read2', function='list_files', arguments={})]
                elif len(calls) == 2:
                    output.message.tool_calls = [ToolCall(id='commit', function='submit_number', arguments={})]
                else:
                    raise AssertionError('ReAct continued after submission')
                return output

            task = Task(dataset=[Sample(input=prompt(100,1))],
                        solver=timed_react(workspace,game,'one',{}), time_limit=15)
            try:
                logs = eval(task,model=get_model('mockllm/model',custom_outputs=respond),
                            log_dir=str(directory/'logs'),display='none')
                self.assertIsNone(logs[0].samples[0].error)
                self.assertEqual(len(calls),2)
                self.assertEqual(calls[0][-1]['role'],'user')
                self.assertIn('0.0 seconds of wall-clock', calls[0][-1]['content'])
                self.assertEqual(calls[1][-1]['role'],'user')
                self.assertIn('42.0 seconds of wall-clock', calls[1][-1]['content'])
                tool_results = [m for m in calls[1] if m['role']=='tool']
                self.assertEqual(sum(bool(m.get('error')) for m in tool_results),1)
                self.assertEqual(game.freeze(),[100])
                audit=[json.loads(line) for line in (directory/'decisions.jsonl').read_text().splitlines()]
                self.assertEqual(len([e for e in audit if e['event']=='tool']),2)
            finally:
                workspace.freeze()


if __name__ == '__main__':
    unittest.main()
