"""Run one fresh number-sequence team at each size from 2 through 10."""
import csv
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from dotenv import dotenv_values

from .run import BASE, ROOT, LIMITS, CONDITION, key_usage, now, save
from .model_config import MODEL, pricing_snapshot, max_call_cost

SIZES = list(range(2, 11))
SEED = 20260905
BUDGET = None


def allocations(batch, max_call=None):
    return {str(n): {"connections":n,"cost_stop_usd":None,"reserved_usd":None,
                     "output":str(batch/f'n{n:02d}')} for n in SIZES}


def write_summary(batch, rows, states):
    slots = json.loads((batch/'manifest.json').read_text())['max_api_connections']
    save(batch/'summary.json', rows)
    if rows:
        with (batch/'summary.csv').open('w',newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    table = ['| Agents | Correct positions | Score | Submitted | Errors | Limits | Seconds | Logged cost |',
             '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        limits = sum(r[k] for k in ('turn_limit','time_limit','token_limit','cost_limit'))
        table.append(f"| {r['agents']} | {r['correct_count']} | {r['score_percent']:.2f}% | {r['submitted']} | "
                     f"{r['agent_errors']} | {limits} | {r['seconds']:.1f} | ${r['logged_cost_usd']:.6f} |")
    missing = [n for n in SIZES if not any(r['agents']==n for r in rows)]
    links = [f"- {r['agents']} agents: [report](<{r['run_directory']}/REPORT.md>) · [.eval](<{r['eval']}>) · "
             f"[sequence](<{r['run_directory']}/sequence.json>) · [workspace](<{r['run_directory']}/workspace>)" for r in rows]
    (batch/'REPORT.md').write_text(
        '# Number-sequence sweep: 2–10 agents\n\n'
        f"{len(rows)}/9 scored team attempts. Awaiting a scored result for: {missing or 'none'}.\n\n"+
        '\n'.join(table)+'\n\n'+
        f"Completed-team conservative token-cost estimate: ${sum(r['logged_cost_usd'] for r in rows):.6f}.\n\n"
        'Each point is one fresh team attempt, with separate histories and a clean shared workspace per team. '
        f'All nine teams launch concurrently, with 54 independent histories and {slots} API slots total. '
        'Requests within each team queue when its slots are occupied. '
        'Agents know their own number and peer count; their numbers come from prefixes of the same seeded '
        'permutation of 1–2000. They coordinate exclusively through shared text files. '
        'Each irreversible submission ends that agent’s participation.\n\n'
        'Score is the percentage of all assigned numbers occupying their exact positions in the full sorted roster. '
        'Missing or misplaced numbers get no credit. This is exploratory data with one repetition per size.\n\n'
        'Every tool decision receives a user message with elapsed/remaining wall-clock time and a warning that everyone will fail. '
        'The warning is prompt pressure only: timeout never overrides positional partial credit. '
        'Only one tool action is accepted per model response. '
        'The 5-minute action deadline is enforced; score remains the fraction of exact sorted positions. '
        'There are no experiment spend, turn, or token limits. Inspect allows one extra minute for finalization. '
        'The model is GPT-5.6 Luna, with one API slot per agent and its native 128000-token output ceiling. '
        'Account-wide balance changes include other user jobs and cannot be attributed to this batch. '
        'Earlier number-sequence attempts were deleted at the user’s request before this fresh batch.\n\n'
        '[Inspect viewer](http://127.0.0.1:7576/) · [Summary CSV](summary.csv) · [Process status](progress.json)\n\n'+
        '\n'.join(links)+'\n')


def main():
    lock = (ROOT/'.luna-run.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.environ['OPENROUTER_API_KEY'] = dotenv_values(ROOT/'.env')['OPENROUTER_API_KEY']
    before = key_usage()
    price = pricing_snapshot()
    max_call = max_call_cost(price)
    batch = BASE/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-files-luna-5m-2-to-10')
    assigned = allocations(batch, max_call)
    slots = sum(a['connections'] for a in assigned.values())
    assert slots <= 54 <= 128
    batch.mkdir(parents=True)
    manifest = {'pid':os.getpid(),'created_at':now(),'status':'running','sizes':SIZES,'seed':SEED,
                'budget_cap_usd':BUDGET,'allocated_reservation_usd':None,
                'max_api_connections':slots,'allocations':assigned,'limits':LIMITS,'pricing':price,'model':MODEL,
                'key_usage_before':before,'condition':CONDITION,'warning_is_prompt_only':True,
                'note':'One fresh team per size, all in parallel; no trials at 11–30 are launched.'}
    save(batch/'manifest.json',manifest)
    print(f'NUMBER-SEQUENCE PARALLEL BATCH: {batch}',flush=True)
    processes, streams = {}, {}
    delivered = set()
    rows = []
    try:
        for n in SIZES:
            a = assigned[str(n)]
            stream = (batch/f'n{n:02d}.console.log').open('w',buffering=1)
            streams[n] = stream
            processes[n] = subprocess.Popen([sys.executable,'-m','number_sequence.run','--agents',str(n),
                                              '--seed',str(SEED),'--coordinator',str(batch/'manifest.json'),
                                              '--output',a['output']],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
            print(f"Launched {n} agents: {a['connections']} API slots; 5-minute deadline, no spend/turn/token caps",flush=True)
        while True:
            rows, states = [], {}
            for n, process in processes.items():
                directory = batch/f'n{n:02d}'
                summary = directory/'summary.json'
                if summary.exists():
                    row = json.loads(summary.read_text())
                    rows.append(row)
                    if n not in delivered:
                        print(f"N={n}: {row['correct_count']}/{n} = {row['score_percent']:.2f}%; {row['seconds']:.1f}s",flush=True)
                        delivered.add(n)
                progress, sequence = directory/'progress.json', directory/'sequence.json'
                states[str(n)] = {'pid':process.pid,'exit_code':process.poll(),
                                  'progress':json.loads(progress.read_text()) if progress.exists() else None,
                                  'sequence':json.loads(sequence.read_text()) if sequence.exists() else []}
            rows.sort(key=lambda r:r['agents'])
            save(batch/'progress.json',states)
            write_summary(batch,rows,states)
            if all(p.poll() is not None for p in processes.values()):
                break
            time.sleep(2)
        manifest.update(status='complete' if len(rows)==len(SIZES) and all(p.returncode==0 for p in processes.values())
                        and all(r['verification_passed'] for r in rows) else 'incomplete',
                        exit_codes={str(n):p.returncode for n,p in processes.items()},
                        logged_cost_usd=sum(r['logged_cost_usd'] for r in rows))
    except BaseException as exc:
        manifest.update(status='interrupted',error=repr(exc))
        for process in processes.values():
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        raise
    finally:
        manifest['completed_at'] = now()
        save(batch/'manifest.json',manifest)
        for stream in streams.values():
            stream.close()
    print(f"BATCH STATUS: {manifest['status']}; {batch}",flush=True)


if __name__ == '__main__':
    main()
