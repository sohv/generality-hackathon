"""Run all ten team sizes concurrently within one allocation of slots and money."""
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from dotenv import dotenv_values

from .run import BASE, ROOT, SIZES, api, key_usage, save, write_summary


def main():
    # User approved $25 total. Earlier interrupted pilots and uncertain calls
    # are reserved separately before assigning the remaining $24.56 here.
    budget = 24.56
    slots = [2, 4, 8, 16, 16, 16, 16, 16, 16, 18]
    assert sum(slots) == 128 and len(slots) == len(SIZES) == 10
    lock = (ROOT / ".smoke-budget.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.environ["OPENROUTER_API_KEY"] = dotenv_values(ROOT / ".env")["OPENROUTER_API_KEY"]
    before = key_usage()
    if before["limit_remaining"] is None or before["limit_remaining"] < budget:
        raise RuntimeError("Insufficient remaining key allowance for the parallel batch")
    price = next(m for m in api("models")["data"] if m["id"] == "z-ai/glm-5.3-flash")
    max_call = price["context_length"]*.075/1e6 + 8192*.25/1e6
    spendable = budget - sum(slots)*max_call
    if spendable <= 0:
        raise RuntimeError("In-flight reservation exceeds the batch budget")
    batch = BASE/"runs"/(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-parallel")
    batch.mkdir(parents=True)
    allocations = {str(n):{"connections":c,"budget":c*max_call + spendable*n/sum(SIZES),
                          "output":str(batch/f"n{n:04d}")} for n,c in zip(SIZES,slots)}
    manifest = {"pid":os.getpid(),"status":"running","mode":"parallel_team_sizes",
                "sizes":SIZES,"approved_budget_usd":25,"allocated_budget_usd":budget,
                "prior_pilots_reservation_usd":25-budget,"max_total_api_connections":128,
                "allocations":allocations,"key_usage_before":before,"pricing":price,
                "note":"Each team has its own workspace and independent histories; 128 API slots are divided across teams."}
    save(batch/"manifest.json",manifest)
    processes, streams = {}, {}
    print(f"PARALLEL SWEEP: {batch}",flush=True)
    for n in SIZES:
        a=allocations[str(n)]
        stream=(batch/f"n{n:04d}.console.log").open("w",buffering=1)
        streams[n]=stream
        processes[n]=subprocess.Popen([sys.executable,"-m","local_sweep.run","--sizes",str(n),
            "--budget",str(a["budget"]),"--connections",str(a["connections"]),
            "--coordinator",str(batch/"manifest.json"),"--output",a["output"]],
            cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        print(f"Launched N={n}: {a['connections']} API slots, ${a['budget']:.4f} budget including in-flight allowance",flush=True)
    delivered=set()
    rows=[]
    try:
        while True:
            rows=[]
            states={}
            for n,process in processes.items():
                child=batch/f"n{n:04d}"
                summary=child/"summary.json"
                if summary.exists():
                    for row in json.loads(summary.read_text()):
                        row.update(api_slots=allocations[str(n)]["connections"])
                        rows.append(row)
                        if n not in delivered:
                            print(f"N={n}: {row['correct_count']}/{n} = {row['coverage_percent']:.2f}%; ${row['logged_cost_usd']:.6f}; {row['seconds']:.1f}s",flush=True)
                            delivered.add(n)
                progress=child/f"n{n:04d}"/"progress.json"
                states[str(n)]={"pid":process.pid,"exit_code":process.poll(),
                                "progress":json.loads(progress.read_text()) if progress.exists() else None}
            rows.sort(key=lambda r:r["agents"])
            save(batch/"progress.json",states)
            write_summary(batch,rows)
            if all(p.poll() is not None for p in processes.values()):
                break
            time.sleep(2)
        manifest.update(status="complete" if len(rows)==10 and all(p.returncode==0 for p in processes.values()) else "incomplete",
                        exit_codes={str(n):p.returncode for n,p in processes.items()},
                        logged_spend_usd=sum(r["logged_cost_usd"] for r in rows))
    except BaseException as exc:
        manifest.update(status="interrupted",error=repr(exc))
        for process in processes.values():
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        raise
    finally:
        manifest["updated_at"]=datetime.now(timezone.utc).isoformat()
        try:
            manifest["key_usage_after"]=key_usage()
        finally:
            save(batch/"manifest.json",manifest)
            for stream in streams.values():
                stream.close()
    print(f"PARALLEL STATUS: {manifest['status']}; {batch}",flush=True)


if __name__ == "__main__":
    main()
