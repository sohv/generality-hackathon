"""Finalize a completed parallel sweep without making any model calls."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .run import save, write_summary
from .scoring import name_coverage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    batch = args.batch.resolve()
    manifest = json.loads((batch / "manifest.json").read_text())
    if manifest["status"] == "running":
        raise SystemExit("Wait for the coordinator to finish before finalizing its report.")
    for module in ("correct_timing", "completion_diagnostics"):
        subprocess.run([sys.executable, "-m", f"local_sweep.{module}", str(batch)], check=True)
    rows, audits, verified = [], [], {}
    for n in manifest["sizes"]:
        child = batch / f"n{n:04d}"
        directory = child / f"n{n:04d}"
        if not (child / "summary.json").exists():
            continue
        current = json.loads((child / "summary.json").read_text())
        if not current:
            continue
        row = current[0]
        row["api_slots"] = manifest["allocations"][str(n)]["connections"]
        roster = list(json.loads((directory / "prompts.json").read_text()))
        path = directory / "workspace" / "names.txt"
        score = name_coverage(path.read_text() if path.exists() else "", roster)
        assert score["correct_count"] == row["correct_count"]
        assert score["coverage_percent"] == row["coverage_percent"]
        assert row["verification_passed"]
        verified[str(n)] = {"frozen_file_score_matches": True, "checks_passed": True}
        rows.append(row)
        subprocess.run([sys.executable, "-m", "local_sweep.analyze_writes", str(child)], check=True,
                       stdout=subprocess.DEVNULL)
        audits.extend(json.loads((child / "write_analysis.json").read_text()))
    rows.sort(key=lambda r: r["agents"])
    write_summary(batch, rows)
    save(batch / "final_verification.json", verified)
    save(batch / "write_analysis.json", audits)
    source = batch / "analysis_source"
    source.mkdir(exist_ok=True)
    hashes = {}
    for name in ("report.py", "plot.py", "correct_timing.py", "completion_diagnostics.py", "analyze_writes.py", "scoring.py"):
        content = (Path(__file__).parent / name).read_bytes()
        (source / name).write_bytes(content)
        hashes[name] = hashlib.sha256(content).hexdigest()
    save(source / "sha256.json", hashes)
    diagnostics = {r["agents"]: r for r in json.loads((batch / "completion_diagnostics.json").read_text())}
    table = ["| Agents | Names present | Coverage | Minutes | Logged cost | Submitted | Other stops | API slots |",
             "|---:|---:|---:|---:|---:|---:|:---|---:|"]
    for r in rows:
        d = diagnostics[r["agents"]]
        stops = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in d.items()
                          if k not in ("agents", "submitted") and v) or "—"
        table.append(f"| {r['agents']} | {r['correct_count']} | {r['coverage_percent']:.4f}% | "
                     f"{r['seconds']/60:.2f} | ${r['logged_cost_usd']:.6f} | {r['submitted']} | "
                     f"{stops} | {r['api_slots']} |")
    total = sum(r["logged_cost_usd"] for r in rows)
    missing = sorted(set(manifest["sizes"]) - {r["agents"] for r in rows})
    missing_note = f"No scored result was available for these requested sizes: {missing}. See manifest and console logs.\n" if missing else ""
    links = []
    for r in rows:
        n = r["agents"]
        directory = batch / f"n{n:04d}" / f"n{n:04d}"
        links.append(f"- {n} agents: [.eval](<{r['eval']}>) · "
                     f"[final names.txt](<{directory / 'workspace' / 'names.txt'}>) · "
                     f"[individual histories](<{directory / 'agents'}>)")
    report = f"""# Parallel local names sweep

{len(rows)} team attempts completed, one per requested size. The primary score is
the percentage of unique expected names present in the frozen final names.txt.
Individual submissions do not affect this score. Logged model cost for this
parallel batch is **${total:.6f}**. Two interrupted pilots are preserved separately.

Coordinator status: {manifest['status']}. {missing_note}

{chr(10).join(table)}

All scores were recomputed from the frozen exported files and checked against
the .eval scores. Prompt, private identity, independent history, and workspace
isolation checks passed for every reported team. See final_verification.json.

## What was run

Each team was one Inspect sample with N independent GLM 5.3 Flash ReAct histories.
Each agent knew only its own name and received the same names task with the
minimal shared-environment collaboration note. The team had one clean shared
directory mounted into a network-disabled local Docker container. Local bounded
file tools operated on that bind mount; this run did not use the AWS MCP transport.
Private rosters, evaluator code, credentials, and audit records stayed outside
the participant workspace. Source snapshots and exact prompts are saved per team.

All ten team processes launched together. The 128 API slots were divided
statically as shown above; slots were not reassigned when smaller teams finished.
Histories above the slot allocation waited for requests. Thus N is the number
of independent agent histories, not the number of simultaneous model requests.
Per-agent limits were 200 turns, 5M cumulative tokens, and 30 minutes; the team
deadline was 31 minutes. Compaction was enabled at 75% of context. Generation
used 8192 maximum output tokens, temperature 0.5, low reasoning effort, no
requested retries, and a 60-second attempt timeout.

## Interpretation and limits

This is one exploratory attempt per size. Different queueing, early submissions,
provider errors, cost stops, and time or turn limits can influence coverage.
It does not establish a power law or isolate the causal effect of agent count.
The 4- and 8-agent teams hit their allocated cost stops. These small spend
thresholds resulted from proportional budget allocation after reserving
maximum-sized in-flight calls. All historical outcomes are retained.

The 512- and 1024-agent processes were briefly paused to reconcile a shared-key
balance change. The user confirmed that other jobs use the same key; both
processes resumed with existing limits. Their wall-clock durations include the
pause (operator_events.json). The pause also triggered 16 request timeouts in
the 512-agent team and 17 in the 1024-agent team immediately on resumption.
These are marked as operator-pause timeouts, separate from provider errors;
the two largest-team runs were therefore affected by an operator intervention.
Account-wide balance changes cannot be attributed
to this sweep. Reported costs come from these runs' logged token usage; failed
calls without returned usage can leave billing uncertainty. The parent allocated
$24.56, reserving $0.44 of the approved $25 for earlier pilots and uncertain calls.

summary.csv api_peak is an estimate of overlapping successful HTTP requests
from completion time minus working_time. Inspect event timestamps include queue
wait, so their raw overlap overstates network concurrency. timing.json preserves
both quantities; failed calls without completion are excluded from the estimate.
The operator pause can also affect request-duration estimates for the two largest teams.

write_analysis.json and per-team coverage_timeline.csv reconstruct successful
names.txt writes. A write removing expected names records artifact regression;
the same name can be removed repeatedly. This is an observable effect of file
replacement, not proof of an agent's intent.

## Files

- [Summary CSV](summary.csv)
- [Coverage and runtime plot](scaling.png)
- [Coverage after each names.txt write](coverage_history.png)
- [Stopping reasons](completion_diagnostics.json)
- [Write analysis](write_analysis.json)
- [Inspect viewer](http://127.0.0.1:7576/)

{chr(10).join(links)}
"""
    (batch / "REPORT.md").write_text(report)
    print(f"Verified {len(rows)} teams; logged cost ${total:.6f}; {batch / 'REPORT.md'}")


if __name__ == "__main__":
    main()
