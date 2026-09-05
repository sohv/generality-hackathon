"""Rerun previously imperfect teams once each, with no overlap between teams."""
import argparse
import csv
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from . import run as runner
from .model_config import MODEL, pricing_snapshot


def write_report(batch, manifest, rows, states):
    runner.save(batch/'summary.json', rows)
    runner.save(batch/'progress.json', states)
    if rows:
        with (batch/'summary.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    table = ['| Agents | Score | Submitted | Deadline | Agent errors | Model errors | Retries | Seconds |',
             '|---:|---:|---:|:---:|---:|---:|---:|---:|']
    for row in rows:
        table.append(f"| {row['agents']} | {row['score_percent']:.2f}% | {row['submitted']} | "
                     f"{row['deadline_reached']} | {row['agent_errors']} | {row['model_errors']} | "
                     f"{row['model_retries']} | {row['seconds']:.1f} |")
    current = [n for n,s in states.items() if s['status']=='running']
    queued = [n for n,s in states.items() if s['status']=='queued']
    links = [f"- {r['agents']} agents: [report](<{r['run_directory']}/REPORT.md>) · [.eval](<{r['eval']}>)"
             for r in rows]
    (batch/'REPORT.md').write_text(
        '# Sequential number-sequence reruns: ten minutes per team\n\n'
        f"Status: **{manifest['status']}**. Running: {current or 'none'}. Queued: {queued or 'none'}.\n\n"
        'Teams were selected because their previous score was below 100%. Each gets one fresh attempt, '
        'in ascending team-size order. No team overlaps another: the previous process exits and removes '
        'its container before the next starts. Agents within each team run concurrently, with one API slot each.\n\n'
        'Model: GPT-5.6 Luna. File-only communication, private unique numbers from 1–2000, disclosed peer count, '
        'and exact sorted-position scoring are unchanged. All initial prompts and repeated clock reminders '
        'state ten minutes from the start. A 600-second common deadline is enforced; Inspect has an extra '
        'minute for finalization. No operator messages, pauses, or deadline changes are planned. '
        'No experiment spend, turn, or cumulative-token caps are set.\n\n'
        + '\n'.join(table) + '\n\n'
        'Provider errors/retries and timeouts are shown separately. Retry counts include repeated logged '
        'requests with the same agent span and last input message ID; Inspect may leave its retries field empty. '
        'A low score can be a valid task outcome; '
        'serial execution cannot guarantee the shared provider is free of throttling. These selected reruns '
        'are a separate condition from the earlier parallel five-minute attempts.\n\n'
        f"[Previous batch](<{manifest['previous_batch']}/REPORT.md>) · "
        '[Live viewer](http://127.0.0.1:7576/) · [Summary CSV](summary.csv) · [Progress](progress.json)\n\n'
        + '\n'.join(links) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--previous', type=Path, default=runner.BASE/'runs/20260905T152921Z-files-luna-unlimited-2-to-10')
    parser.add_argument('--minutes', type=int, default=10)
    args = parser.parse_args()
    previous = args.previous.resolve()
    prior_rows = json.loads((previous/'summary.json').read_text())
    sizes = sorted(r['agents'] for r in prior_rows if r['score_percent'] < 100)
    if not sizes:
        raise ValueError('No previous scores below 100% to rerun')
    runner.configure_time_limit(args.minutes)
    lock = (runner.ROOT/'.luna-run.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.environ['OPENROUTER_API_KEY'] = dotenv_values(runner.ROOT/'.env')['OPENROUTER_API_KEY']
    before, price = runner.key_usage(), pricing_snapshot()
    seed = json.loads((previous/'manifest.json').read_text())['seed']
    batch = runner.BASE/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                               +f'-files-luna-sequential-{args.minutes}m-{sizes[0]}-to-{sizes[-1]}')
    batch.mkdir(parents=True)
    assigned = {str(n):{'connections':n,'cost_stop_usd':None,'reserved_usd':None,
                       'output':str(batch/f'n{n:02d}')} for n in sizes}
    manifest = {'pid':os.getpid(),'status':'running','created_at':runner.now(),'model':MODEL,
                'previous_batch':str(previous),'selection_rule':'previous score below 100%; one fresh attempt each',
                'previous_scores':{str(r['agents']):r['score_percent'] for r in prior_rows},
                'sizes':sizes,'seed':seed,'minutes':args.minutes,'limits':dict(runner.LIMITS),
                'condition':runner.CONDITION,'execution':'sequential_teams_concurrent_agents',
                'max_concurrent_teams':1,'max_api_connections':max(sizes),'allocations':assigned,
                'key_usage_before':before,'pricing':price,'source_sha256':{}}
    for path in runner.BASE.glob('*.py'):
        dest = batch/'source'/path.name
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(path.read_bytes())
        manifest['source_sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    runner.save(batch/'manifest.json', manifest)
    states = {str(n):{'status':'queued','pid':None,'exit_code':None} for n in sizes}
    rows, process = [], None
    write_report(batch,manifest,rows,states)
    print(f'SEQUENTIAL BATCH: {batch}',flush=True)
    try:
        for n in sizes:
            directory = Path(assigned[str(n)]['output'])
            states[str(n)].update(status='starting',started_at=runner.now())
            with (batch/f'n{n:02d}.console.log').open('w', buffering=1) as console:
                process = subprocess.Popen([sys.executable,'-m','number_sequence.run','--agents',str(n),
                    '--seed',str(seed),'--minutes',str(args.minutes),'--coordinator',str(batch/'manifest.json'),
                    '--output',str(directory)],cwd=runner.ROOT,stdout=console,stderr=subprocess.STDOUT)
                states[str(n)].update(status='running',pid=process.pid)
                print(f'START N={n}: {args.minutes} minutes, {n} concurrent agents; all other teams queued',flush=True)
                while process.poll() is None:
                    for file,key in [('progress.json','progress'),('sequence.json','sequence')]:
                        path = directory/file
                        if path.exists():
                            states[str(n)][key] = json.loads(path.read_text())
                    write_report(batch,manifest,rows,states)
                    time.sleep(2)
                states[str(n)].update(status='completed' if process.returncode==0 else 'error',
                                      exit_code=process.returncode,completed_at=runner.now())
                summary = directory/'summary.json'
                if summary.exists():
                    row = json.loads(summary.read_text())
                    rows.append(row)
                    print(f"FINISH N={n}: {row['score_percent']:.2f}%; submitted {row['submitted']}/{n}; "
                          f"deadline={row['deadline_reached']}; model errors={row['model_errors']}; "
                          f"retries={row['model_retries']}",flush=True)
                else:
                    print(f'FINISH N={n}: infrastructure failure, exit {process.returncode}; console retained',flush=True)
                write_report(batch,manifest,rows,states)
                process = None
        ordered = [states[str(n)] for n in sizes]
        no_overlap = all(a['completed_at'] <= b['started_at'] for a,b in zip(ordered,ordered[1:]))
        manifest.update(status='complete' if len(rows)==len(sizes) and all(r['verification_passed'] for r in rows)
                        and all(s['exit_code']==0 for s in states.values()) else 'incomplete',
                        no_team_overlap_verified=no_overlap,logged_cost_usd=sum(r['logged_cost_usd'] for r in rows))
    except BaseException as exc:
        manifest.update(status='interrupted',error=repr(exc))
        if process and process.poll() is None:
            process.send_signal(signal.SIGINT)
        raise
    finally:
        manifest['completed_at'] = runner.now()
        runner.save(batch/'manifest.json',manifest)
        write_report(batch,manifest,rows,states)
    print(f"BATCH {manifest['status']}: {batch}",flush=True)


if __name__ == '__main__':
    main()
