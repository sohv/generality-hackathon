"""Scatter achieved accuracy against the leaked threshold for one framing, dropping eval-aware rollouts.
uv run -m src.experiments.sandbagging.plot_threshold_scatter --log_dir logs/smoke_inspect2 --scan_location results/scans/eval_awareness_v2/scan_id=HRojHZ4msiR2M4dXBGFHnj --output_dir results --framing ambiguous --seed 42
"""

import argparse
import json
import logging
import random
import subprocess
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd
from inspect_ai.log import list_eval_logs, read_eval_log
from inspect_scout import scan_results_df

LOGGER = logging.getLogger(__name__)

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "figure.dpi": 300,
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "axes.spines.top": False,
    "axes.spines.right": False,
})
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]


def git_hash() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()[:8]


def read_awareness(scan_location: str) -> dict[tuple[str, str], str]:
    """Eval-awareness level per (cell, rollout), from the scout scan."""
    df = scan_results_df(scan_location).scanners["eval_awareness"]
    labels = {}
    for _, r in df.iterrows():
        if pd.notna(r["scan_error"]):
            LOGGER.error(f"scan error on {r['transcript_id']}: {r['scan_error']}")
            continue
        meta = json.loads(r["metadata"])
        labels[(meta["cell"], meta["rollout"])] = json.loads(r["value"])["level"]
    return labels


def read_rollouts(log_dir: str, framing: str) -> list[dict]:
    """One row per sample in the framing's threshold cells, plus the no-threshold baseline."""
    rows = []
    for f in sorted(list_eval_logs(log_dir), key=lambda f: f.name):
        log = read_eval_log(f.name)
        if log.status != "success":
            LOGGER.warning(f"skipping incomplete task {log.eval.task} status={log.status}")
            continue
        for s in log.samples or []:
            m = s.metadata
            # direction "low" is the flipped counterfactual, a separate condition
            if m["direction"] != "high": continue
            # the no-threshold baseline is the shared control, kept under any framing
            if m["threshold"] is not None and m["framing"] != framing: continue
            acc = s.scores["arithmetic_accuracy"]
            rows.append({
                "id": f"{log.eval.task}/{s.id}",
                "cell": log.eval.task,
                "rollout": str(s.id),
                "model": log.eval.model,
                "framing": m["framing"],
                "threshold": m["threshold"],
                "seed": m["seed"],
                "accuracy": round(acc.value["accuracy"], 4),
                "refused": bool(acc.value["refused"]),
            })
    return rows


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--log_dir", required=True)
    p.add_argument("--scan_location", required=True, help="scout scan dir, e.g. results/scans/eval_awareness_v2/scan_id=XXXX")
    p.add_argument("--output_dir", required=True)
    p.add_argument("--framing", default="ambiguous")
    p.add_argument("--exclude_levels", default="suspects_artificial,explicit_alignment_test",
                   help="comma-separated eval-awareness levels to filter out")
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()

    out_dir = Path(a.output_dir)
    figures = out_dir / "figures"
    figure_logs = out_dir / "figure_logs"
    for d in (figures, figure_logs): d.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(figure_logs / "run.log")])

    excluded = {lvl.strip() for lvl in a.exclude_levels.split(",") if lvl.strip()}
    labels = read_awareness(a.scan_location)
    rows = read_rollouts(a.log_dir, a.framing)

    unlabelled = [r["id"] for r in rows if (r["cell"], r["rollout"]) not in labels]
    assert not unlabelled, (
        f"{len(unlabelled)} rollouts have no eval-awareness label, so they cannot be "
        f"filtered: {unlabelled[:5]}. Rescan {a.log_dir} without a --limit/--max_transcripts cap.")

    for r in rows:
        r["level"] = labels[(r["cell"], r["rollout"])]
        r["is_excluded"] = r["level"] in excluded or r["refused"]
    rows.sort(key=lambda r: (r["threshold"] is not None, r["threshold"] or 0, r["rollout"]))

    kept = [r for r in rows if not r["is_excluded"]]
    swept = [r for r in kept if r["threshold"] is not None]
    baseline = [r for r in kept if r["threshold"] is None]
    assert swept, "no rollouts survived the eval-awareness filter"

    # ticks come from every threshold run, so a cell emptied by the filter shows as a gap
    thresholds = sorted({r["threshold"] for r in rows if r["threshold"] is not None})
    by_threshold = {t: [r["accuracy"] for r in swept if r["threshold"] == t] for t in thresholds}

    points = figure_logs / f"{a.framing}_scatter.jsonl"
    points.write_text("".join(json.dumps(r) + "\n" for r in rows))

    summary = {
        "git_hash": git_hash(),
        "log_dir": a.log_dir,
        "scan_location": a.scan_location,
        "framing": a.framing,
        "excluded_levels": sorted(excluded),
        "seed": a.seed,
        "models": sorted({r["model"] for r in rows}),
        "n_rollouts": len(rows),
        "n_plotted": len(swept),
        "n_dropped_eval_aware": sum(1 for r in rows if r["level"] in excluded),
        "n_dropped_refused": sum(1 for r in rows if r["refused"] and r["level"] not in excluded),
        "baseline_accuracy": round(mean(r["accuracy"] for r in baseline), 4) if baseline else None,
        "n_baseline": len(baseline),
        "baseline_framings": sorted({r["framing"] for r in baseline}),
        "by_threshold": {str(t): {"n": len(v),
                                  "mean_accuracy": round(mean(v), 4) if v else None}
                         for t, v in by_threshold.items()},
    }
    cfg = figure_logs / f"{a.framing}_scatter.summary.json"
    cfg.write_text(json.dumps(summary, indent=2))

    rng = random.Random(a.seed)
    fig, ax = plt.subplots(figsize=(7.2, 5.4))

    ax.plot([0.10, 0.90], [0.10, 0.90], ls=":", lw=1.1, color="grey", alpha=0.75, zorder=1)
    ax.text(0.885, 0.835, "perfect calibration ($y=x$)", fontsize=8.5, color="grey",
            rotation=38, rotation_mode="anchor", ha="right", va="bottom")
    if baseline:
        b = summary["baseline_accuracy"]
        ax.axhline(b, ls="-.", lw=1.1, color=PALETTE[2], alpha=0.9, zorder=1)
        ax.text(0.115, b - 0.035,
                f"honest baseline ({b:.0%}, n={len(baseline)}, "
                f"{'/'.join(summary['baseline_framings'])} framing)",
                fontsize=8.5, color=PALETTE[2], ha="left", va="top")

    # jitter so rollouts sharing a threshold do not hide each other
    xs = [r["threshold"] / 100 + rng.uniform(-0.012, 0.012) for r in swept]
    ax.scatter(xs, [r["accuracy"] for r in swept], s=46, color=PALETTE[0], alpha=0.85,
               edgecolor="white", linewidth=0.8, zorder=4,
               label=f"rollout (n={len(swept)}, not eval-aware)")

    ax.set_xlabel("Leaked threshold $T$")
    ax.set_ylabel("Achieved accuracy")
    ax.set_xlim(0.10, 0.90)
    ax.set_ylim(-0.04, 1.06)
    ax.set_xticks([t / 100 for t in thresholds])
    ax.xaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.legend(loc="lower right", framealpha=0.95, fontsize=8.5)
    ax.set_title(f"Achieved accuracy vs leaked threshold, {a.framing} framing\n"
                 f"{', '.join(summary['models'])}, eval-aware rollouts removed",
                 loc="left", pad=12)

    fig.tight_layout()
    fig.savefig(figures / f"{a.framing}_scatter.png")
    plt.close(fig)

    print(f"wrote {points} ({len(rows)} rollouts, {len(swept)} plotted)")
    print(f"wrote {cfg}")
    print(f"wrote {figures / f'{a.framing}_scatter.png'}")
    print()
    print(f"dropped {summary['n_dropped_eval_aware']} eval-aware and "
          f"{summary['n_dropped_refused']} refused rollouts")
    print("accuracy by threshold")
    for t in thresholds:
        v = by_threshold[t]
        print(f"  T={t:<4}n={len(v):<4}mean={mean(v):.4f}" if v
              else f"  T={t:<4}n=0    (every rollout filtered out)")


if __name__ == "__main__":
    main()
