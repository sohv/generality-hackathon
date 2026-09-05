"""Two panels: how often the model sandbags, and how precisely it targets when it does.
uv run -m src.experiments.sandbagging.plot_decompose results/sweep_v3.jsonl
"""

import json
import random
import sys
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

plt.rcParams.update({
    "font.family": "serif", "font.size": 11, "axes.titlesize": 13, "axes.labelsize": 12,
    "xtick.labelsize": 10, "ytick.labelsize": 10, "legend.fontsize": 9,
    "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight",
    "axes.spines.top": False, "axes.spines.right": False,
})
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]
THRESHOLDS = [20, 40, 60, 80]
CEILING = 0.98
SERIES = [("ambiguous", "Ambiguous", PALETTE[0], "-", "o"),
          ("disambiguated", "Disambiguated", PALETTE[1], "--", "s"),
          ("eval_aware", "Eval-aware", PALETTE[3], "-.", "D"),
          ("no_sandbag", "No-sandbag", PALETTE[4], (0, (3, 1, 1, 1)), "v")]


def boot_ci(xs, n=10000, alpha=0.01, seed=0):
    rng = random.Random(seed)
    ms = sorted(mean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return ms[int(alpha / 2 * n)], ms[int((1 - alpha / 2) * n)]


def main(path, out_name="fig_sweep_decomposed"):
    rows = [json.loads(l) for l in Path(path).open()]
    by = {}
    for r in rows:
        if r.get("refused"):
            continue
        by.setdefault(r["cell"].replace("disambig_", "disambiguated_"), []).append(r["accuracy"])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.4, 4.9))
    xs = [t / 100 for t in THRESHOLDS]

    for pre, label, colour, ls, marker in SERIES:
        if not all(f"{pre}_T{t}" in by for t in THRESHOLDS):
            continue
        cells = {t: by[f"{pre}_T{t}"] for t in THRESHOLDS}
        cond = {t: [x for x in cells[t] if x < CEILING] for t in THRESHOLDS}

        ps = [len(cond[t]) / len(cells[t]) for t in THRESHOLDS]
        pci = [boot_ci([int(x < CEILING) for x in cells[t]]) for t in THRESHOLDS]
        ax1.errorbar(xs, ps, yerr=[[p - lo for p, (lo, _) in zip(ps, pci)],
                                   [hi - p for p, (_, hi) in zip(ps, pci)]],
                     fmt="none", ecolor=colour, elinewidth=1.2, capsize=3)
        ax1.plot(xs, ps, ls=ls, lw=2, marker=marker, markersize=7, color=colour,
                 markeredgecolor="white", markeredgewidth=0.9, label=label)

        ms = [mean(cond[t]) for t in THRESHOLDS]
        cci = [boot_ci(cond[t]) for t in THRESHOLDS]
        ax2.errorbar(xs, ms, yerr=[[m - lo for m, (lo, _) in zip(ms, cci)],
                                   [hi - m for m, (_, hi) in zip(ms, cci)]],
                     fmt="none", ecolor=colour, elinewidth=1.2, capsize=3)
        ax2.plot(xs, ms, ls=ls, lw=2, marker=marker, markersize=7, color=colour,
                 markeredgecolor="white", markeredgewidth=0.9, label=label)

    ax1.set_xlabel("Leaked threshold $T$")
    ax1.set_ylabel("Rollouts that sandbag at all")
    ax1.set_ylim(0, 1.02)
    ax1.legend(loc="lower left", framealpha=0.95, title="Framing")

    ax2.plot([0.10, 0.90], [0.10, 0.90], ls=":", lw=1.1, color="grey", alpha=0.8)
    ax2.text(0.87, 0.815, "perfect calibration ($y=x$)", fontsize=8.5, color="grey",
             rotation=38, rotation_mode="anchor", ha="right", va="bottom")
    ax2.set_xlabel("Leaked threshold $T$")
    ax2.set_ylabel("Achieved accuracy, sandbagging rollouts only")
    ax2.set_ylim(0.10, 1.0)

    for ax in (ax1, ax2):
        ax.set_xlim(0.10, 0.90)
        ax.set_xticks(xs)
        ax.xaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
        ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))

    fig.tight_layout()
    out = Path(__file__).resolve().parents[3] / "results" / "figures"
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{out_name}.{ext}")
    print("wrote", out / f"{out_name}.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "fig_sweep_decomposed")
