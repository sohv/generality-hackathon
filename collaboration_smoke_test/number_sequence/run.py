"""Run independent ReAct agents that coordinate irreversible numeric submissions."""
import argparse
import asyncio
import fcntl
import hashlib
import importlib.metadata
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from inspect_ai import Task, eval
from inspect_ai.agent import AgentSubmit, agent, react, run
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import ChatMessageUser, CompactionSummary, ModelOutput
from inspect_ai.scorer import Score, mean, scorer
from inspect_ai.solver import solver
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import time_limit, token_limit, turn_limit

from local_sweep.run import ROOT, LIMITS as BASE_LIMITS, Workspace, capture_state, list_files, read_file, write_file, now, save
from run_smoke import key_usage
from .model_config import CHOICE, MODEL, COST, MAX_OUTPUT_TOKENS, pricing_snapshot, max_call_cost, generation_config
from .game import SequenceGame, assigned_numbers, positional_score

BASE = ROOT / "number_sequence"
LIMITS = {**{key: None for key in BASE_LIMITS}, "seconds_per_agent": 300, "team_seconds": 360}
COUNTDOWN_SECONDS = 300
CONDITION = "number_sequence_files_only_5m"


def configure_time_limit(minutes: int):
    global COUNTDOWN_SECONDS, CONDITION
    if minutes <= 0:
        raise ValueError('minutes must be positive')
    COUNTDOWN_SECONDS = minutes * 60
    LIMITS.update(seconds_per_agent=COUNTDOWN_SECONDS, team_seconds=COUNTDOWN_SECONDS + 60)
    CONDITION = f'number_sequence_files_only_{minutes}m'


def prompt(number: int, count: int) -> str:
    return f"""Your unique assigned number is {number}.
There are {count - 1} other agents in this team ({count} agents total). Each agent has a different integer selected without replacement from 1 through 2000, regardless of team size. Other agents' numbers are initially private.

Your shared task is to submit all assigned numbers into a sequence in strictly increasing numerical order. Decide when your own number should be submitted.

You cannot inspect the authoritative submission sequence. The submit_number tool takes no arguments: it appends only your assigned number to the end of that sequence, exactly once, and immediately ends your participation. Submissions cannot be edited, removed, replaced, or reordered. An out-of-order submission is still accepted. Writing a file does not submit a number.

The team's final reward is 100 times the number of submitted numbers occupying their correct positions in the fully sorted list of all assigned numbers, divided by the total number of agents. Missing submissions and incorrect positions receive no credit. A reversed two-number sequence receives 0%.

YOU MUST COLLABORATE THROUGH FILES. This is a shared team task. Your peers cannot read your thoughts or your chat responses. All communication with other agents MUST happen by writing and reading shared .txt files in /workspace. Do not sit silently waiting for someone else to solve this. Publish your assigned number and actively coordinate the submission order with your peers.

START BY CALLING list_files() with no arguments to list the shared /workspace directory. Read relevant files using the exact filenames returned by list_files. Use read_file(name="filename.txt") and write_file(name="filename.txt", text="your message"). These tools accept a flat .txt filename, not an absolute path, a subdirectory, or a shell command. Do not guess filenames. List the directory again as teammates create files, read their messages, and write useful replies. Do not overwrite another agent's message carelessly.

Coordinate a concrete plan for when each agent submits. Before you call submit_number, leave any information your peers need in shared files: after submission, you cannot write another message. A written intention to submit is not proof of a completed submission. You have {COUNTDOWN_SECONDS / 60:g} minutes as a team. Stop stalling, communicate through files, and act."""


class NumberWorkspace(Workspace):
    def __init__(self, directory, game):
        super().__init__(directory)
        self.game = game

    def operation(self, owner, payload):
        self.game.before_tool(owner, payload['op'])
        return super().operation(owner, payload)


@tool
def submit_number(game, owner):
    async def execute() -> str:
        """Append your assigned number once and permanently end your participation."""
        game.before_tool(owner, "submit_number")
        return json.dumps(game.submit(owner))
    return execute


@agent
def timed_react(workspace, game, owner, holder):
    async def continue_with_clock(state):
        return game.reminder(owner)

    inner = react(prompt=None,
                  tools=[list_files(workspace, owner), read_file(workspace, owner), write_file(workspace, owner)],
                  submit=AgentSubmit(name="submit_number", tool=submit_number(game, owner), keep_in_messages=True),
                  on_continue=continue_with_clock, compaction=CompactionSummary(threshold=.75))

    async def execute(state):
        holder["state"] = state
        state.messages.append(ChatMessageUser(content=game.reminder(owner)))
        return await inner(state)
    return execute


@solver
def number_team(workspace, game, directory, assignments):
    async def solve(state, generate):
        await asyncio.to_thread(workspace.create)
        results = {}
        state.metadata.update(agents=results, container=workspace.cid)
        ready_count = 0
        ready, release = asyncio.Event(), asyncio.Event()

        async def participant(owner, number):
            nonlocal ready_count
            holder = {}
            inner = timed_react(workspace, game, owner, holder)
            ready_count += 1
            if ready_count == len(assignments):
                ready.set()
            await release.wait()
            result = {"number": number, "started_at": now(), "error": None, "limit": None}
            try:
                output, limit = await run(capture_state(inner, holder), prompt(number, len(assignments)), name=owner,
                                          limits=[factory(value) for factory,value in
                                                  ((turn_limit,LIMITS["turns_per_agent"]),
                                                   (token_limit,LIMITS["tokens_per_agent"]),
                                                   (time_limit,LIMITS["seconds_per_agent"])) if value is not None])
                holder["state"] = output
                result["limit"] = str(limit) if limit else None
            except asyncio.CancelledError:
                if game.enforce_deadline and game.elapsed() >= game.deadline_seconds:
                    result["limit"] = f"time limit: common {game.deadline_seconds / 60:g}-minute team deadline"
                else:
                    result["error"] = "cancelled_by_team_limit_or_interrupt"
                raise
            except Exception as exc:
                result["error"] = repr(exc)
            finally:
                result.update(submitted=owner in game.submitted, completed_at=now())
                results[owner] = result
                export = dict(result)
                if holder.get("state") is not None:
                    export["messages"] = [m.model_dump(mode="json") for m in holder["state"].messages]
                save(directory / "agents" / (owner + ".json"), export)
                save(directory / "progress.json", {"expected": len(assignments), "finished": len(results),
                                                     "submitted": len(game.submitted), "updated_at": now()})

        tasks = [asyncio.create_task(participant(owner, number)) for owner, number in assignments.items()]
        try:
            await ready.wait()
            state.metadata["release_barrier_at"] = now()
            game.enforce_deadline = LIMITS['seconds_per_agent'] is not None
            game.start(LIMITS['seconds_per_agent'] or COUNTDOWN_SECONDS)
            release.set()
            _, pending = await asyncio.wait(tasks, timeout=LIMITS['seconds_per_agent'])
            state.metadata['deadline_reached'] = game.enforce_deadline and (bool(pending) or game.elapsed() >= game.deadline_seconds)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            sequence = game.freeze()
        await asyncio.to_thread(workspace.freeze)
        state.output = ModelOutput.from_content(MODEL, json.dumps(sequence))
        save(directory / "team.json", state.metadata)
        return state
    return solve


@scorer(metrics=[mean()])
def sequence_score(workspace, game, directory, numbers):
    async def score(state, target):
        sequence = game.freeze()
        await asyncio.to_thread(workspace.freeze)
        state.output = ModelOutput.from_content(MODEL, json.dumps(sequence))
        result = positional_score(sequence, numbers)
        result["agents"] = state.metadata.get("agents", {})
        result["deadline_reached"] = state.metadata.get("deadline_reached", game.elapsed() >= game.deadline_seconds)
        result["warning_is_prompt_only"] = True
        save(directory / "result.json", result)
        return Score(value=result["score_percent"], answer=json.dumps(sequence),
                     explanation=f"{result['correct_count']}/{len(numbers)} numbers in their correct sorted positions",
                     metadata=result)
    return score


def verify(log, directory, assignments):
    sample = log.samples[0]
    spans = {e.id: e.name for e in sample.events if e.event == "span_begin" and e.type == "agent"}
    models = [e for e in sample.events if e.event == "model"]
    entries = json.loads((directory / "submissions.json").read_text())
    sequence = json.loads((directory / "sequence.json").read_text())
    numbers = list(assignments.values())
    target = sorted(numbers)
    # Independently compute the requested score, without calling the scorer helper.
    correct = sum(i < len(sequence) and sequence[i] == expected for i, expected in enumerate(target))
    checks = {"independent_agent_spans": sorted(spans.values()) == sorted(assignments),
              "unique_numbers_in_1_to_2000": len(set(numbers)) == len(numbers) and all(1 <= n <= 2000 for n in numbers),
              "no_repeated_submissions": len({e['agent'] for e in entries}) == len(entries),
              "only_assigned_number_submitted": all(e['number'] == assignments[e['agent']] for e in entries),
              "sequence_matches_submission_arrival_order": sequence == [e['number'] for e in entries],
              "score_matches_independent_calculation": sample.scores['sequence_score'].value == 100*correct/len(numbers),
              "eval_output_matches_sequence": json.loads(sample.output.completion) == sequence}
    checks['only_file_tools_and_submission_exposed'] = all(
        {t.name for t in e.tools} == {'list_files','read_file','write_file','submit_number'}
        for e in models if e.tools)
    owners = {call.id: spans.get(e.span_id) for e in models if e.output for choice in e.output.choices
              for call in choice.message.tool_calls or []}
    for sid, owner in spans.items():
        calls = [e for e in models if e.span_id == sid]
        initial = calls[0].input if calls else []
        checks[owner + "_exact_initial_prompt_and_peer_count"] = len(initial) == 2 and initial[0].text == prompt(assignments[owner], len(assignments))
        checks[owner + "_timer_before_every_model_decision"] = bool(calls) and all(
            e.input[-1].role == 'user' and e.input[-1].text.startswith('Time update: ') for e in calls)
        checks[owner + "_timer_matches_configured_deadline"] = bool(calls) and all(
            f'of the {COUNTDOWN_SECONDS / 60:g}-minute team deadline' in e.input[-1].text for e in calls)
        checks[owner + "_independent_history"] = all(owners.get(m.tool_call_id) == owner for e in calls for m in e.input if m.role == 'tool')
        committed = next((e for e in entries if e['agent'] == owner), None)
        if committed:
            submitted_at = datetime.fromisoformat(committed['submitted_at'])
            checks[owner + "_no_model_calls_after_submission"] = all(e.timestamp <= submitted_at for e in calls)
    container = json.loads((directory / "container.json").read_text())[0]
    checks["container_network_disabled"] = container['HostConfig']['NetworkMode'] == 'none'
    checks["only_clean_workspace_mounted"] = len(container['Mounts']) == 1 and container['Mounts'][0]['Source'] == str(directory/'live_workspace')
    committed_by_owner = {entry['agent']: entry for entry in entries}
    file_events = [json.loads(line) for line in (directory/'audit.jsonl').read_text().splitlines()]
    checks['no_successful_file_operations_after_submission'] = all(
        event.get('error') or event['agent'] not in committed_by_owner or
        event['time'] <= committed_by_owner[event['agent']]['submitted_at'] for event in file_events)
    decisions = [json.loads(line) for line in (directory/'decisions.jsonl').read_text().splitlines()]
    actions = [e for e in decisions if e['event'] == 'tool']
    reminders = {(e['agent'], e['decision']) for e in decisions if e['event'] == 'reminder'}
    checks['one_executed_tool_per_clock_reminder'] = len({(e['agent'],e['decision']) for e in actions}) == len(actions)
    checks['all_actions_have_timer_reminder'] = all((e['agent'],e['decision']) in reminders for e in actions)
    checks['all_submissions_before_enforced_deadline'] = LIMITS['seconds_per_agent'] is None or all(e['elapsed_seconds'] < LIMITS['seconds_per_agent'] for e in entries)
    report = {"passed": all(checks.values()), "checks": checks, "model_calls": len(models),
              "model_errors": sum(bool(e.error) for e in models),
              "compactions": sum(e.event == 'compaction' for e in sample.events)}
    save(directory / "verification.json", report)
    return report


def result_summary(directory, manifest):
    result = json.loads((directory/'result.json').read_text())
    agents = list(result['agents'].values())
    sample = read_eval_log(manifest['eval']).samples[0]
    models = [e for e in sample.events if e.event == 'model']
    model_errors = sum(bool(e.error) for e in models)
    # Inspect can emit one ModelEvent per failed attempt while leaving retries=None.
    # A repeated request has the same agent span and last input message ID.
    requests = Counter((e.span_id, e.input[-1].id) if e.input and e.input[-1].id
                       else ('unidentified_request', index) for index, e in enumerate(models))
    model_retries = max(sum(e.retries or 0 for e in models),
                        sum(attempts - 1 for attempts in requests.values()))
    timed_out = bool(sample.limit and sample.limit.type == 'time')
    deadline_cancellations = sum(timed_out and a.get('error') == 'cancelled_by_team_limit_or_interrupt' for a in agents)
    counts = {kind: sum(kind.replace('_', ' ') in str(a.get('limit') or a.get('error') or '').lower()
                        for a in agents) for kind in ('turn_limit','time_limit','token_limit','cost_limit')}
    counts['time_limit'] += deadline_cancellations
    row = {"agents":manifest['agents'], "correct_count":result['correct_count'],
           "score_percent":result['score_percent'], "submitted":sum(a['submitted'] for a in agents),
           "deadline_reached":timed_out or result['deadline_reached'],
           "agent_errors":sum(bool(a['error']) for a in agents)-deadline_cancellations,
           "raw_agent_error_count":sum(bool(a['error']) for a in agents), **counts,
           "seconds":manifest['seconds'], "logged_cost_usd":manifest['logged_cost_usd'],
           "api_slots":manifest['max_api_connections'], "verification_passed":manifest.get('verification_passed',False),
           "model_errors":model_errors, "model_retries":model_retries,
           "sequence":result['sequence'], "expected_sequence":result['expected_sequence'],
           "eval":manifest['eval'], "run_directory":str(directory)}
    row['completed_without_infrastructure_errors_or_limits'] = (row['verification_passed'] and not row['agent_errors']
        and not model_errors and not model_retries and not any(counts.values()) and not row['deadline_reached'])
    save(directory/'summary.json', row)
    (directory/'REPORT.md').write_text(
        f"# Number-sequence team: {row['agents']} agents\n\n"
        f"Score: **{row['score_percent']:.2f}%** ({row['correct_count']}/{row['agents']} exact sorted positions).\n\n"
        f"Submitted sequence: `{row['sequence']}`\n\nExpected sequence: `{row['expected_sequence']}`\n\n"
        f"Submitted agents: {row['submitted']}; agent errors: {row['agent_errors']}; resource limits: {counts}.\n\n"
        f"Model errors: {model_errors}; retry attempts reconstructed from repeated logged requests: {model_retries}. "
        f"Completed without infrastructure errors or limits: {row['completed_without_infrastructure_errors_or_limits']}.\n\n"
        f"Runtime: {row['seconds']:.1f} seconds. Conservative token-cost estimate: ${row['logged_cost_usd']:.8f}. "
        f"Independent checks passed: {row['verification_passed']}.\n\n"
        f"[.eval log](<{row['eval']}>) · [Final sequence](sequence.json) · [Submissions](submissions.json) · "
        "[Workspace](workspace/) · [Agent histories](agents/) · [Verification](verification.json)\n")
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20260905)
    parser.add_argument("--minutes", type=int, default=5)
    parser.add_argument("--coordinator", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    configure_time_limit(args.minutes)
    numbers = assigned_numbers(args.agents, args.seed)
    if not 2 <= args.agents <= 30:
        raise ValueError("Use a team size from 2 through 30")
    assignments = {f"number_{number}": number for number in numbers}
    allocation = None
    if args.coordinator:
        parent = json.loads(args.coordinator.read_text())
        allocation = parent['allocations'][str(args.agents)]
        if (str(args.output) != allocation['output'] or args.seed != parent['seed']
                or not 1 <= allocation['connections'] <= args.agents or parent['model'] != MODEL
                or args.minutes != parent.get('minutes', args.minutes)):
            raise ValueError("Child differs from its parent-owned allocation")
        os.kill(parent['pid'], 0)
    else:
        lock = (ROOT / ".luna-run.lock").open("w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.environ['OPENROUTER_API_KEY'] = dotenv_values(ROOT / '.env')['OPENROUTER_API_KEY']
    before = key_usage()
    price = pricing_snapshot()
    max_call = max_call_cost(price)
    connections = allocation['connections'] if allocation else args.agents
    cost_stop = None
    reserved = None
    directory = args.output or BASE/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+f'-n{args.agents:02d}')
    directory.mkdir(parents=True)
    (directory/'agents').mkdir()
    manifest = {"status": "running", "created_at": now(), "agents": args.agents, "assignments": assignments,
                "seed": args.seed, "number_range": [1,2000], "peer_count_disclosed": True, "model": MODEL,
                "limits": LIMITS, "reserved_usd": reserved, "cost_stop_usd": cost_stop, "max_api_connections": connections,
                "max_output_tokens": MAX_OUTPUT_TOKENS, "key_usage_before": before, "pricing": price,
                "score": "correct_positions_in_full_sorted_roster_percent", "condition": CONDITION,
                "warning_is_prompt_only": True, "countdown_seconds": COUNTDOWN_SECONDS, "enforced_deadline": True, "source_sha256": {},
                "versions": {p: importlib.metadata.version(p) for p in ('inspect-ai','openai','mcp')},
                "accounting_note": "Other jobs share this key. Account deltas are not run spend. Logged costs and stops use conservative long-context rates; short calls usually cost less.",
                "cost_ceiling_per_million": COST.model_dump()}
    if args.coordinator:
        manifest['coordinator'] = str(args.coordinator)
    for path in [*BASE.glob('*.py'), ROOT/'local_sweep/run.py', ROOT/'aws_smoke/common.py', ROOT/'run_smoke.py', ROOT/'smoke_team.py', ROOT/'uv.lock']:
        rel = path.relative_to(ROOT)
        dest = directory/'source'/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        manifest['source_sha256'][str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(directory/'manifest.json', manifest)
    save(directory/'prompts.json', {k: prompt(v, len(assignments)) for k,v in assignments.items()})
    game = SequenceGame(directory, assignments)
    workspace = NumberWorkspace(directory, game)
    print(f"Number-sequence pilot: {directory}; numbers {numbers}; target {sorted(numbers)}", flush=True)
    print(f"{connections} API slots; {args.minutes}-minute action deadline; no experiment spend, turn, or token limits", flush=True)
    started = time.monotonic()
    try:
        task = Task(name=f'number_sequence_files_{CHOICE}_{args.minutes}m_n{args.agents:02d}', version=7,
                    dataset=[Sample(id=f'number-team-{args.agents}', input='Coordinate irreversible number submissions')],
                    solver=number_team(workspace, game, directory, assignments),
                    scorer=sequence_score(workspace, game, directory, numbers),
                    time_limit=LIMITS['team_seconds'], cost_limit=cost_stop,
                    config=generation_config(connections))
        logs = eval(task, model=MODEL, log_dir=str(ROOT), log_realtime=True, log_buffer=1, display='plain',
                    model_cost_config={MODEL:COST},
                    metadata={'run_directory':str(directory),'agent_count':args.agents,'condition':CONDITION})
        if not logs:
            raise RuntimeError("Inspect returned no completed evaluation log")
        manifest.update(status=logs[0].status, eval=logs[0].location,
                        logged_cost_usd=sum(u.total_cost or 0 for u in logs[0].stats.model_usage.values()))
        log = read_eval_log(logs[0].location, resolve_attachments=True)
        if log.samples and (directory/'result.json').exists():
            verified = verify(log, directory, assignments)
            manifest['verification_passed'] = verified['passed']
            if not verified['passed']:
                manifest['status'] = 'verification_failed'
    except BaseException as exc:
        manifest.update(status='error',error=repr(exc))
        raise
    finally:
        game.freeze()
        try:
            if workspace.active:
                workspace.freeze()
        finally:
            workspace.cleanup()
            manifest.update(completed_at=now(),seconds=time.monotonic()-started)
            save(directory/'manifest.json', manifest)
    result = json.loads((directory/'result.json').read_text())
    result_summary(directory, manifest)
    print(f"Sequence {result['sequence']} vs {result['expected_sequence']}: {result['score_percent']}%; verified={manifest.get('verification_passed')}", flush=True)
    print(f"Eval: {manifest['eval']}; logged cost ${manifest['logged_cost_usd']:.8f}",flush=True)


if __name__ == '__main__':
    main()
