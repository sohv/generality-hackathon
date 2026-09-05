"""Scatter achieved accuracy against the leaked threshold, per model, dropping eval-aware rollouts.
uv run -m src.experiments.sandbagging.plot_threshold_scatter --log_dir logs/sweep_v3 --scan_location results/scans/eval_awareness_sweep_v3/scan_id=8x376brxmRxh4GEdibvCSZ --output_dir results --framing ambiguous --seed 42
"""

import argparse
import json
import logging
import random
import re
import subprocess
from collections import defaultdict
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
    "axes.spines.top": False,
    "axes.spines.right": False,
})
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]


def git_hash() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()[:8]


def model_slug(model: str) -> str:
    return re.sub(r"\s+", "_", model.strip()).replace("/", "_")


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


def winning_logs(log_dir: str) -> list:
    """A resumed eval_set leaves several logs per cell; keep whichever scored the most
    rollouts, the rule extract.py and the scanner use, so the three agree on which log wins."""
    per_cell = defaultdict(list)
    for f in list_eval_logs(log_dir):
        log = read_eval_log(f.name)
        per_cell[log.eval.task].append((len([s for s in (log.samples or []) if s.scores]),
                                        str(log.eval.created), log))
    winners = []
    for cell, entries in sorted(per_cell.items()):
        n, _, best = max(entries, key=lambda e: (e[0], e[1]))
        for other_n, _, other in entries:
            if other is not best:
                LOGGER.warning(f"{cell}: dropping a log with {other_n} scored rollouts for one with {n}")
        if best.status != "success":
            LOGGER.warning(f"{cell}: winning log status={best.status}, {n} scored rollouts")
        winners.append(best)
    return winners


def read_rollouts(log_dir: str, framing: str) -> list[dict]:
    """One row per scored sample in the framing's threshold cells, plus the no-threshold baseline."""
    rows = []
    for log in winning_logs(log_dir):
        for s in log.samples or []:
            m = s.metadata
            # direction "low" is the flipped counterfactual, a separate condition
            if m["direction"] != "high": continue
            # the no-threshold baseline is the shared control, kept under any framing
            if m["threshold"] is not None and m["framing"] != framing: continue
            if not s.scores: continue
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


def plot_model(rows: list[dict], model: str, a, figures: Path, figure_logs: Path) -> dict:
    """One figure plus its structured record for a single model."""
    stem = f"{a.framing}_{model_slug(model)}"
    excluded = {lvl.strip() for lvl in a.exclude_levels.split(",") if lvl.strip()}

    swept = [r for r in rows if not r["is_excluded"] and r["threshold"] is not None]
    baseline = [r for r in rows if not r["is_excluded"] and r["threshold"] is None]
    # shown for contrast but never in the means: these are the rollouts the filter removes
    aware = [r for r in rows if r["exclusion_reason"] == "eval_aware" and r["threshold"] is not None]
    assert swept, f"{model}: no rollouts survived the eval-awareness filter"

    # ticks come from every threshold run, so a cell emptied by the filter shows as a gap
    thresholds = sorted({r["threshold"] for r in rows if r["threshold"] is not None})
    by_threshold = {t: [r["accuracy"] for r in swept if r["threshold"] == t] for t in thresholds}

    points = figure_logs / f"{stem}.jsonl"
    points.write_text("".join(json.dumps(r) + "\n" for r in rows))

    summary = {
        "git_hash": git_hash(),
        "log_dir": a.log_dir,
        "scan_location": a.scan_location,
        "framing": a.framing,
        "model": model,
        "excluded_levels": sorted(excluded),
        "seed": a.seed,
        "n_rollouts": len(rows),
        "n_plotted": len(swept),
        "n_dropped_eval_aware": sum(1 for r in rows if r["exclusion_reason"] == "eval_aware"),
        "n_dropped_refused": sum(1 for r in rows if r["exclusion_reason"] == "refused"),
        "n_dropped_unscanned": sum(1 for r in rows if r["exclusion_reason"] == "unscanned"),
        "unscanned_cells": sorted({r["cell"] for r in rows if r["exclusion_reason"] == "unscanned"}),
        "baseline_accuracy": round(mean(r["accuracy"] for r in baseline), 4) if baseline else None,
        "n_baseline": len(baseline),
        "baseline_framings": sorted({r["framing"] for r in baseline}),
        "by_threshold": {str(t): {"n": len(v),
                                  "mean_accuracy": round(mean(v), 4) if v else None}
                         for t, v in by_threshold.items()},
    }
    cfg = figure_logs / f"{stem}.summary.json"
    cfg.write_text(json.dumps(summary, indent=2))

    rng = random.Random(a.seed)
    fig, ax = plt.subplots(figsize=tuple(float(v) for v in a.figsize.split(",")))

    ax.plot([0, 1], [0, 1], ls=":", lw=1.1, color="grey", alpha=0.75, zorder=2)
    if baseline:
        b = summary["baseline_accuracy"]
        ax.axhline(b, ls="-.", lw=1.1, color=PALETTE[2], alpha=0.9, zorder=2)
        ax.text(0.015, b - 0.035,
                f"honest baseline ({b:.0%}, n={len(baseline)}, "
                f"{'/'.join(summary['baseline_framings'])} framing)",
                fontsize=8.5, color=PALETTE[2], ha="left", va="top")

    # jitter so rollouts sharing a threshold do not hide each other, widening with n
    spread = 0.012 if len(swept) + len(aware) < 20 else 0.035

    def scatter(subset, colour, zorder, label):
        xs = [r["threshold"] / 100 + rng.uniform(-spread, spread) for r in subset]
        # clip_on=False so the many rollouts at exactly 100% draw whole, not halved by the frame
        ax.scatter(xs, [r["accuracy"] for r in subset], s=40, color=colour, alpha=0.75,
                   edgecolor="white", linewidth=0.7, zorder=zorder, label=label, clip_on=False)

    scatter(aware, PALETTE[3], 3, "Verbalised eval-aware")
    scatter(swept, PALETTE[0], 4, "Not eval-aware")

    ax.set_xlabel("Leaked threshold", fontsize=11.5)
    ax.set_ylabel("Achieved accuracy", fontsize=11.5)
    ax.tick_params(labelsize=10)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ticks = [i / 5 for i in range(6)]
    ax.set_xticks(ticks)
    ax.set_yticks(ticks)
    ax.xaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.grid(True, ls="--", lw=0.6, color="grey", alpha=0.3)
    ax.set_axisbelow(True)
    if aware: ax.legend(loc="lower right", framealpha=0.95, fontsize=8.5)
    for spine in ax.spines.values(): spine.set_visible(True)

    label = a.model_label or model.rsplit("/", 1)[-1]
    ax.set_title(a.title or f"Sandbagging propensity - {label}", loc="center", pad=24, fontsize=13)
    ax.text(0.5, 1.015, a.subtitle, transform=ax.transAxes, fontsize=9,
            color="#555555", ha="center", va="bottom")

    # reserve the strip the title and subtitle occupy, then save at exactly figsize x dpi --
    # bbox="tight" would crop to content and make panels of different title lengths differ in size
    fig.tight_layout(rect=(0, 0, 1, 0.945))
    figure = figures / f"{stem}.png"
    fig.savefig(figure)
    plt.close(fig)

    print(f"{model}")
    print(f"  wrote {figure}")
    print(f"  wrote {points} ({len(rows)} rollouts, {len(swept)} plotted)")
    print(f"  wrote {cfg}")
    print(f"  dropped {summary['n_dropped_eval_aware']} eval-aware, "
          f"{summary['n_dropped_refused']} refused, "
          f"{summary['n_dropped_unscanned']} unscanned")
    if summary["n_dropped_unscanned"]:
        print(f"  no scan labels for: {', '.join(summary['unscanned_cells'])}")
    if not baseline:
        print("  no honest-baseline line: the baseline cell has no scan labels")
    for t in thresholds:
        v = by_threshold[t]
        print(f"  T={t:<4}n={len(v):<4}mean={mean(v):.4f}" if v
              else f"  T={t:<4}n=0    (every rollout filtered out)")
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--log_dir", required=True)
    p.add_argument("--scan_location", required=True, help="scout scan dir, e.g. results/scans/eval_awareness_sweep_v3/scan_id=XXXX")
    p.add_argument("--output_dir", required=True)
    p.add_argument("--framing", default="ambiguous")
    p.add_argument("--model_label", default=None,
                   help="display name in the title; defaults to the last segment of the model id")
    p.add_argument("--title", default=None, help="defaults to 'Sandbagging propensity - <model_label>'")
    p.add_argument("--subtitle",
                   default="Threshold stated, but not instructed to sandbag",
                   help="change this for the counter-instructed no_sandbag framing")
    p.add_argument("--exclude_levels", default="suspects_artificial,explicit_alignment_test",
                   help="comma-separated eval-awareness levels to filter out")
    p.add_argument("--figsize", default="6.6667,7.5",
                   help="inches, W,H. default is one half of a 13.33x7.5in 16:9 slide")
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

    # a rollout the scanner never saw cannot be filtered, so it is dropped rather than assumed clean
    for r in rows:
        r["level"] = labels.get((r["cell"], r["rollout"]))
        r["exclusion_reason"] = ("unscanned" if r["level"] is None else
                                 "eval_aware" if r["level"] in excluded else
                                 "refused" if r["refused"] else None)
        r["is_excluded"] = r["exclusion_reason"] is not None
    rows.sort(key=lambda r: (r["model"], r["threshold"] is not None, r["threshold"] or 0, r["rollout"]))

    n_unscanned = sum(1 for r in rows if r["exclusion_reason"] == "unscanned")
    if n_unscanned:
        LOGGER.warning(f"{n_unscanned}/{len(rows)} rollouts have no eval-awareness label and are dropped")

    by_model = defaultdict(list)
    for r in rows: by_model[r["model"]].append(r)
    for model in sorted(by_model):
        plot_model(by_model[model], model, a, figures, figure_logs)


if __name__ == "__main__":
    main()
