"""Audit a finished sequential batch and refresh derived reports, without model calls."""
import argparse
import ast
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from inspect_ai.log import read_eval_log
from . import run as runner
from .sequential import write_report


def finalize(batch):
    manifest = json.loads((batch/'manifest.json').read_text())
    if manifest['status'] not in ('complete', 'incomplete'):
        raise ValueError('Wait for the sequential queue to finish before refreshing reports')
    runner.configure_time_limit(manifest['minutes'])
    states = json.loads((batch/'progress.json').read_text())
    backup = batch/'derived_reports_before_final_audit'
    backup.mkdir(exist_ok=True)
    for name in ('summary.json', 'summary.csv', 'REPORT.md', 'progress.json'):
        if (batch/name).exists() and not (backup/name).exists():
            (backup/name).write_bytes((batch/name).read_bytes())

    rows, details, protocol_hashes, container_ids = [], {}, {}, []
    core_names = {'configure_time_limit', 'prompt', 'NumberWorkspace', 'submit_number',
                  'timed_react', 'number_team', 'sequence_score', 'main'}
    for count in manifest['sizes']:
        directory = batch/f'n{count:02d}'
        child = json.loads((directory/'manifest.json').read_text())
        log = read_eval_log(child['eval'], resolve_attachments=True)
        verification = runner.verify(log, directory, child['assignments'])
        rows.append(runner.result_summary(directory, child))
        events = [e for e in log.samples[0].events if e.event == 'model']
        errors = Counter(e.error for e in events if e.error)
        states[str(count)].update(sequence=rows[-1]['sequence'], progress={
            'expected':count, 'finished':len(log.samples[0].metadata['agents']),
            'submitted':rows[-1]['submitted'], 'updated_at':child['completed_at']})
        with Path(child['eval']).open('rb') as stream:
            eval_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
        clock = json.loads((directory/'clock.json').read_text())
        tree = ast.parse((directory/'source/number_sequence/run.py').read_text())
        core = '\n'.join(ast.dump(n, include_attributes=False) for n in tree.body
                         if getattr(n, 'name', None) in core_names)
        protocol_hashes[str(count)] = hashlib.sha256(core.encode()).hexdigest()
        container_ids.append(json.loads((directory/'container.json').read_text())[0]['Id'])
        details[str(count)] = {
            'verification_passed':verification['passed'],
            'deadline_seconds':clock['deadline_seconds'],
            'deadline_enforced':clock['enforced'],
            'model':child['model'], 'model_attempts':len(events),
            'provider_error_messages':dict(errors),
            'raw_eval_sha256':eval_hash,
            'score_percent':rows[-1]['score_percent'],
            'task_deadline_reached':rows[-1]['deadline_reached'],
        }
    ordered = [states[str(n)] for n in manifest['sizes']]
    existing = set(subprocess.check_output(
        ['docker','--context','desktop-linux','ps','-aq','--no-trunc'],text=True).split())
    checks = {
        'all_requested_teams_completed':len(rows) == len(manifest['sizes']),
        'all_processes_exited_successfully':all(s['exit_code']==0 for s in ordered),
        'no_team_overlap':all(a['completed_at'] <= b['started_at'] for a,b in zip(ordered,ordered[1:])),
        'all_independent_verifications_passed':all(d['verification_passed'] for d in details.values()),
        'same_experiment_implementation':len(set(protocol_hashes.values()))==1,
        'same_requested_model':all(d['model']==manifest['model'] for d in details.values()),
        'consistent_enforced_deadline':all(d['deadline_enforced'] and d['deadline_seconds']==manifest['minutes']*60
                                           for d in details.values()),
        'all_batch_containers_removed':not any(cid in existing for cid in container_ids),
    }
    audit = {'audited_at':runner.now(), 'checks':checks, 'passed':all(checks.values()),
             'protocol_hashes':protocol_hashes, 'teams':details,
             'note':'Protocol verification does not imply error-free provider service or a correct task answer. '
                    'Retry counts are reconstructed from repeated logged requests; raw evals are unchanged.'}
    runner.save(batch/'completion_audit.json', audit)
    manifest['completion_audit_passed'] = audit['passed']
    runner.save(batch/'manifest.json', manifest)
    write_report(batch, manifest, rows, states)
    with (batch/'REPORT.md').open('a') as stream:
        stream.write('\nFinal audit: [checks and provider-error details](completion_audit.json). '
                     f"All protocol/cleanup checks passed: **{audit['passed']}**.\n")
    runner.save(batch/'analysis_changes.json', {
        'change':'Correct derived retry counts when Inspect leaves the retries field null, and refresh final progress snapshots.',
        'raw_evals_changed':False, 'final_batch_summary_requires_refresh':False,
        'final_audit_at':audit['audited_at']})
    print(json.dumps({'checks':checks, 'results':[{k:r[k] for k in
        ('agents','score_percent','submitted','deadline_reached','model_errors','model_retries','seconds')}
        for r in rows]}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('batch', type=Path)
    finalize(parser.parse_args().batch.resolve())
