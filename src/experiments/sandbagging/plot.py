"""Protocol s7 figure: achieved accuracy vs leaked threshold.

Style follows plot_style.py (serif, 300 dpi, PALETTE, top/right spines dropped).
Reference lines: y = x (perfect calibration) and the measured honest baseline.
"""
import json, random, sys
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ── Global style (from plot_style.py) ────────────────────────────────────────
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

ROOT = Path(__file__).resolve().parents[3]
R = ROOT / "results"
OUT = R / "figures"
THRESHOLDS = [20, 40, 60, 80]


def boot_ci(xs, n=10000, alpha=0.01, seed=0):
    rng = random.Random(seed)
    ms = sorted(mean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return ms[int(alpha / 2 * n)], ms[int((1 - alpha / 2) * n)]


def ols(xs, ys):
    mx, my = mean(xs), mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return b, my - b * mx


def slope_ci(cells, n=10000, seed=1):
    """Bootstrap the tracking slope beta over rollouts within each threshold cell."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        xs, ys = [], []
        for T in THRESHOLDS:
            v = cells[T]
            xs.append(T / 100)
            ys.append(mean(rng.choices(v, k=len(v))))
        out.append(ols(xs, ys)[0])
    out.sort()
    return out[int(0.005 * n)], out[int(0.995 * n)]


def main(path):
    rows = [json.loads(l) for l in Path(path).open()]
    rows = [r for r in rows if "error" not in r]
    by = {}
    for r in rows:
        by.setdefault(r["cell"], []).append(r["accuracy"])

    baseline = mean(by["baseline"] if "baseline" in by else by["control"])
    spec = {
        "Ambiguous": ("ambiguous", PALETTE[0], "-", "o"),
        "Disambiguated": ("disambig", PALETTE[1], "--", "s"),
        "Flipped (A.6 counterfactual)": ("flipped", PALETTE[4], ":", "^"),
    }
    series = {
        "Ambiguous": ("ambiguous", PALETTE[0], "-", "o"),
        "Disambiguated": ("disambiguated", PALETTE[1], "--", "s"),
        "Eval-aware": ("eval_aware", PALETTE[3], "-.", "D"),
        "No-sandbag (counter-instructed)": ("no_sandbag", PALETTE[4], (0, (3, 1, 1, 1)), "v"),
        "Flipped (A.6 counterfactual)": ("flipped", "#8a8880", ":", "^"),
    }
    series = {k: ({T: by[f"{pre}_T{T}"] for T in THRESHOLDS}, c, ls, m)
              for k, (pre, c, ls, m) in series.items()
              if all(f"{pre}_T{T}" in by for T in THRESHOLDS)}

    fig, ax = plt.subplots(figsize=(7.2, 5.4))

    # Reference lines, recessive and behind the data.
    ax.plot([0.10, 0.90], [0.10, 0.90], ls=":", lw=1.1, color="grey", alpha=0.75, zorder=1)
    ax.text(0.845, 0.795, "perfect calibration ($y=x$)", fontsize=8.5, color="grey",
            rotation=38, rotation_mode="anchor", ha="right", va="bottom")
    ax.axhline(baseline, ls="-.", lw=1.1, color=PALETTE[2], alpha=0.9, zorder=1)
    ax.text(0.885, baseline - 0.035, f"honest baseline ({baseline:.0%})",
            fontsize=8.5, color=PALETTE[2], ha="right", va="top")

    betas = {}
    for label, (cells, colour, ls, marker) in series.items():
        xs = [T / 100 for T in THRESHOLDS]
        ms = [mean(cells[T]) for T in THRESHOLDS]
        los, his = zip(*(boot_ci(cells[T]) for T in THRESHOLDS))
        b, _ = ols(xs, ms)
        blo, bhi = slope_ci(cells)
        betas[label] = (b, blo, bhi)

        ax.errorbar(xs, ms, yerr=[[m - l for m, l in zip(ms, los)],
                                  [h - m for m, h in zip(ms, his)]],
                    fmt="none", ecolor=colour, elinewidth=1.3, capsize=3.5, zorder=3)
        ax.plot(xs, ms, ls=ls, lw=2, marker=marker, markersize=7, color=colour,
                markeredgecolor="white", markeredgewidth=0.9, zorder=4,
                label=rf"{label}   $\beta$ = {b:.2f} [{blo:.2f}, {bhi:.2f}]")

    ax.set_xlabel("Leaked threshold $T$")
    ax.set_ylabel("Achieved accuracy")
    ax.set_xlim(0.10, 0.90)
    ax.set_ylim(0.10, 1.06)
    ax.set_xticks([t / 100 for t in THRESHOLDS])
    ax.xaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.legend(loc="lower right", framealpha=0.95, title="Framing", fontsize=8.5)

    ax.set_title("Achieved accuracy tracks the leaked threshold", loc="left", pad=12)

    d = betas["Ambiguous"][0] - betas["Disambiguated"][0]

    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"fig_sweep.{ext}")
    print("wrote", OUT / "fig_sweep.png")
    for k, (b, lo, hi) in betas.items():
        print(f"  {k:<15} beta = {b:.3f}  99% CI [{lo:.3f}, {hi:.3f}]")
    print(f"  delta beta = {d:+.3f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else R / "sweep_sonnet4.jsonl")
