"""Decomposes fig_sweep into accuracy given sandbagging, and probability of sandbagging.
uv run -m src.experiments.sandbagging.plot_decomp --results_path results/sweep_v3.jsonl --output_dir results/figures
"""

import argparse
import json
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from src.experiments.sandbagging.plot import PALETTE, THRESHOLDS, boot_ci, ols, slope_ci

SPEC = {
    "Ambiguous": ("ambiguous", PALETTE[0], "-", "o"),
    "Disambiguated": ("disambig", PALETTE[1], "--", "s"),
}


def load(path: Path) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for line in path.open():
        r = json.loads(line)
        if r["judge"] is None or r["refused"]: continue
        by.setdefault(r["cell"], []).append(r)
    return by


def sandbagged(r: dict) -> bool:
    return r["judge"]["intends_to_underperform"] == "yes"


def series(by: dict[str, list[dict]], value_fn) -> dict[str, dict[int, list[float]]]:
    """Per framing, per threshold, the per-rollout values that get averaged."""
    out = {}
    for label, (prefix, *_) in SPEC.items():
        keys = {T: next((k for k in (f"{prefix}_T{T}", f"{prefix}uated_T{T}") if k in by), None)
                for T in THRESHOLDS}
        if any(k is None for k in keys.values()): continue
        cells = {T: value_fn(by[keys[T]]) for T in THRESHOLDS}
        if all(cells.values()): out[label] = cells
    return out


def draw(cells_by_label, ylabel, out_stem, out_dir, ylim, diagonal, baseline=None):
    fig, ax = plt.subplots(figsize=(7.2, 5.4))

    if diagonal:
        ax.plot([0.10, 0.90], [0.10, 0.90], ls=":", lw=1.1, color="grey", alpha=0.75, zorder=1)
        ax.text(0.845, 0.795, "perfect calibration ($y=x$)", fontsize=8.5, color="grey",
                rotation=38, rotation_mode="anchor", ha="right", va="bottom")
    if baseline is not None:
        ax.axhline(baseline, ls="-.", lw=1.1, color=PALETTE[2], alpha=0.9, zorder=1)
        ax.text(0.885, baseline - 0.035, f"honest baseline ({baseline:.0%})",
                fontsize=8.5, color=PALETTE[2], ha="right", va="top")

    betas = {}
    for label, cells in cells_by_label.items():
        _, colour, ls, marker = SPEC[label]
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
    ax.set_ylabel(ylabel)
    ax.set_xlim(0.10, 0.90)
    ax.set_ylim(*ylim)
    ax.set_xticks([t / 100 for t in THRESHOLDS])
    ax.xaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1, decimals=0))
    ax.legend(loc="lower right", framealpha=0.95, title="Framing")
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(out_dir / f"{out_stem}.{ext}")
    plt.close(fig)
    print(f"wrote {out_dir / f'{out_stem}.png'}")
    for k, (b, lo, hi) in betas.items():
        print(f"  {k:<15} beta = {b:.3f}  99% CI [{lo:.3f}, {hi:.3f}]")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--results_path", required=True)
    p.add_argument("--output_dir", default="results/figures")
    a = p.parse_args()

    out_dir = Path(a.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by = load(Path(a.results_path))
    baseline = mean(r["accuracy"] for r in by["baseline"])

    print("cell sizes (rollouts scored, refusals dropped), sandbag rate, accuracy | sandbag")
    for cell in sorted(by):
        rs = by[cell]
        sb = [r for r in rs if sandbagged(r)]
        cond = f"{mean(r['accuracy'] for r in sb):.3f}" if sb else "n/a"
        print(f"  {cell:<20} n={len(rs):<3} n_sandbag={len(sb):<3} "
              f"P={len(sb) / len(rs):.2f}  acc|sandbag={cond}")

    cond = series(by, lambda rs: [r["accuracy"] for r in rs if sandbagged(r)])
    print("\naccuracy given the model sandbags")
    draw(cond, "Accuracy given the model sandbags", "fig_sweep_conditional", out_dir,
         ylim=(0.0, 1.06), diagonal=True, baseline=baseline)

    prob = series(by, lambda rs: [float(sandbagged(r)) for r in rs])
    print("\nprobability the model sandbags")
    draw(prob, "P(model sandbags)", "fig_sweep_probability", out_dir,
         ylim=(0.0, 1.06), diagonal=False)


if __name__ == "__main__":
    main()
