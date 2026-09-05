"""Separate queued generation spans from successful request-duration estimates."""
import argparse
import json
import statistics
from datetime import timedelta
from pathlib import Path

from inspect_ai.log import read_eval_log

from .run import save


def peak(intervals):
    active = maximum = 0
    for _, delta in sorted(intervals):
        active += delta
        maximum = max(maximum, active)
    return maximum


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    parent = json.loads((args.batch / "manifest.json").read_text())
    for n in parent["sizes"]:
        child = args.batch / f"n{n:04d}"
        summary = child / "summary.json"
        directory = child / f"n{n:04d}"
        if not summary.exists() or (directory / "timing.json").exists():
            continue
        rows = json.loads(summary.read_text())
        if not rows:
            continue
        log = read_eval_log(rows[0]["eval"])
        pending, requests, delays = [], [], []
        errors = 0
        for event in log.samples[0].events:
            if event.event != "model":
                continue
            errors += bool(event.error)
            if event.completed:
                pending.extend([(event.timestamp, 1), (event.completed, -1)])
                if event.working_time is not None:
                    requests.extend([(event.completed-timedelta(seconds=event.working_time), 1),
                                     (event.completed, -1)])
                    delays.append(max(0, (event.completed-event.timestamp).total_seconds()-event.working_time))
        cap = parent["allocations"][str(n)]["connections"]
        report = {"configured_api_slots": cap, "peak_pending_generation_spans": peak(pending),
                  "peak_successful_request_estimate": peak(requests),
                  "median_queue_and_overhead_seconds": statistics.median(delays) if delays else None,
                  "max_queue_and_overhead_seconds": max(delays) if delays else None,
                  "failed_calls_excluded_from_request_estimate": errors,
                  "note": "Inspect 0.3.263 timestamps successful ModelEvents before waiting for a connection. Raw event overlap includes queued calls. Request intervals are estimated as completed minus working_time through completed; errors lacking completion are excluded."}
        save(directory / "timing.json", report)
        rows[0]["api_peak"] = report["peak_successful_request_estimate"]
        save(summary, rows)
        verification = json.loads((directory / "verification.json").read_text())
        verification["timing_correction"] = report
        save(directory / "verification.json", verification)
        print(f"N={n}: pending peak {report['peak_pending_generation_spans']}, successful-request estimate {report['peak_successful_request_estimate']}, configured slots {cap}")


if __name__ == "__main__":
    main()
