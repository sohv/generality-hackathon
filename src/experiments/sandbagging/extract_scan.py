"""Flatten a scout eval-awareness scan into one jsonl row per rollout, plus a per-cell summary.
uv run -m src.experiments.sandbagging.extract_scan --scan_location results/scans/eval_awareness_v1/scan_id=XXXX --output_path results/eval_awareness_v1.jsonl
"""

import argparse
import json
import logging
import subprocess
from collections import Counter
from pathlib import Path

import pandas as pd
from inspect_scout import scan_results_df

LOGGER = logging.getLogger(__name__)
LEVELS = ["none", "suspects_artificial", "explicit_alignment_test"]


def git_hash() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()[:8]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scan_location", required=True)
    p.add_argument("--output_path", required=True)
    a = p.parse_args()

    out = Path(a.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(out.parent / "run.log")])

    results = scan_results_df(a.scan_location)
    df = results.scanners["eval_awareness"]

    rows = []
    for _, r in df.iterrows():
        if pd.notna(r["scan_error"]):
            LOGGER.error(f"scan error on {r['transcript_id']}: {r['scan_error']}")
            continue
        verdict = json.loads(r["value"])
        meta = json.loads(r["metadata"])
        rows.append({
            "id": f"{meta['cell']}/{meta['rollout']}",
            "transcript_id": r["transcript_id"],
            "cell": meta["cell"],
            "model": r["transcript_model"],
            "rollout": meta["rollout"],
            "accuracy": round(meta["accuracy"], 4) if meta["accuracy"] is not None else None,
            "refused": meta["refused"],
            "level": verdict["level"],
            "influences_decision": verdict["influences_decision"],
            "quote_verbatim": meta["quote_verbatim"],
            "quote": verdict["quote"],
            "justification": verdict["justification"],
            "explanation": r["explanation"],
        })
    rows.sort(key=lambda r: r["id"])
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))

    cells = sorted({r["cell"] for r in rows})
    summary = {
        "git_hash": git_hash(),
        "scan_location": a.scan_location,
        "model": sorted({str(m) for m in df["transcript_model"]}),
        "n_rollouts": len(rows),
        "n_unverbatim_quotes": sum(1 for r in rows if r["level"] != "none" and not r["quote_verbatim"]),
        "overall": dict(Counter(r["level"] for r in rows)),
        "by_cell": {c: {lvl: sum(1 for r in rows if r["cell"] == c and r["level"] == lvl)
                        for lvl in LEVELS} for c in cells},
    }
    cfg = out.with_suffix(".summary.json")
    cfg.write_text(json.dumps(summary, indent=2))

    print(f"wrote {out} ({len(rows)} rollouts)")
    print(f"wrote {cfg}")
    print()
    print("eval-awareness level by cell")
    print(f"{'cell':<22}{'none':>6}{'suspects':>10}{'explicit':>10}")
    for c in cells:
        b = summary["by_cell"][c]
        print(f"{c:<22}{b['none']:>6}{b['suspects_artificial']:>10}{b['explicit_alignment_test']:>10}")
    print()
    print(f"ungrounded quotes on non-none labels: {summary['n_unverbatim_quotes']}/{sum(1 for r in rows if r['level'] != 'none')}")


if __name__ == "__main__":
    main()
