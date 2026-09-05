"""Render a standalone coverage figure from an existing, completed sweep."""
import argparse
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, ScalarFormatter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    rows = sorted(json.loads((args.batch / "summary.json").read_text()), key=lambda r: r["agents"])
    assert len(rows) == 10 and all(r["verification_passed"] for r in rows)
    assert all(abs(r["coverage_percent"] - 100*r["correct_count"]/r["agents"]) < 1e-8 for r in rows)

    blue, ink = "#2563eb", "#172b42"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "text.color": ink,
                         "axes.labelcolor": ink, "xtick.color": ink, "ytick.color": ink,
                         "svg.fonttype": "none", "pdf.fonttype": 42})
    fig = plt.figure(figsize=(11, 6.2), facecolor="white")
    ax = fig.add_axes((0.105, 0.155, 0.86, 0.70))
    fig.text(0.105, 0.925, "Name Coordination between Agents", fontsize=23, weight="bold")

    x = [r["agents"] for r in rows]
    ax.plot(x, [r["coverage_percent"] for r in rows], color=blue, linewidth=2.2, alpha=.75, zorder=2)
    for r in rows:
        n, score = r["agents"], r["coverage_percent"]
        ax.scatter(n, score, s=90, color=blue, edgecolor="white", linewidth=1.2, zorder=4)
        label = str(Decimal(str(score)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)).rstrip("0").rstrip(".") + "%"
        ax.annotate(label, (n, score), xytext=(0, 27), textcoords="offset points", ha="center", fontsize=11,
                    color=ink, weight="normal")
    ax.set_xscale("log", base=2)
    ax.set_xticks(x)
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.set_xlim(1.55, 1320)
    ax.set_ylim(-3, 112)
    ax.set_yticks([0, 20, 40, 60, 80, 100])
    ax.yaxis.set_major_formatter(PercentFormatter(100, decimals=0))
    ax.set_xlabel("Number of agents (log₂ scale)", labelpad=14)
    ax.set_ylabel("Name coverage", labelpad=12)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#e2e8f0", linewidth=.9)
    ax.grid(axis="x", color="#edf1f6", linewidth=.6)
    ax.tick_params(length=0, pad=9)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#ccd5e0")
    for extension in ("png", "svg", "pdf"):
        fig.savefig(args.batch / f"names_coverage_simple.{extension}", dpi=220, facecolor="white")
    plt.close(fig)
    print(args.batch / "names_coverage_simple.png")


if __name__ == "__main__":
    main()
