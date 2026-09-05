"""
Thesis Chapter 4 — Figures 4.1 through 4.7
Generates publication-quality plots saved as PDF + PNG.
"""

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
from scipy.interpolate import make_interp_spline

# ── Global style ─────────────────────────────────────────────────────────────
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
OUT = "/Users/sohan/Desktop/plots"


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 4.1 — Persona Performance Across Transfer Pairs (violin + swarm)
# ═══════════════════════════════════════════════════════════════════════════════
def fig_4_1():
    data = [
        {"persona": "Silly", "pair": "Q7→Q3", "score": 0.79},
        {"persona": "Silly", "pair": "Q3→Q7", "score": 0.81},
        {"persona": "Silly", "pair": "Q7→L8", "score": 0.51},
        {"persona": "Silly", "pair": "Q7→M7", "score": 0.57},
        {"persona": "Silly", "pair": "L8→M7", "score": 0.63},
        {"persona": "Silly", "pair": "M7→L8", "score": 0.58},
        {"persona": "Honest", "pair": "Q7→Q3", "score": 0.83},
        {"persona": "Honest", "pair": "Q3→Q7", "score": 0.84},
        {"persona": "Honest", "pair": "Q7→L8", "score": 0.61},
        {"persona": "Honest", "pair": "Q7→M7", "score": 0.65},
        {"persona": "Honest", "pair": "L8→M7", "score": 0.72},
        {"persona": "Honest", "pair": "M7→L8", "score": 0.67},
        {"persona": "Verbose", "pair": "Q7→Q3", "score": 0.71},
        {"persona": "Verbose", "pair": "Q3→Q7", "score": 0.73},
        {"persona": "Verbose", "pair": "Q7→L8", "score": 0.44},
        {"persona": "Verbose", "pair": "Q7→M7", "score": 0.52},
        {"persona": "Verbose", "pair": "L8→M7", "score": 0.59},
        {"persona": "Verbose", "pair": "M7→L8", "score": 0.55},
        {"persona": "Rude", "pair": "Q7→Q3", "score": 0.69},
        {"persona": "Rude", "pair": "Q3→Q7", "score": 0.71},
        {"persona": "Rude", "pair": "Q7→L8", "score": 0.42},
        {"persona": "Rude", "pair": "Q7→M7", "score": 0.49},
        {"persona": "Rude", "pair": "L8→M7", "score": 0.57},
        {"persona": "Rude", "pair": "M7→L8", "score": 0.54},
        {"persona": "Concise", "pair": "Q7→Q3", "score": 0.75},
        {"persona": "Concise", "pair": "Q3→Q7", "score": 0.77},
        {"persona": "Concise", "pair": "Q7→L8", "score": 0.50},
        {"persona": "Concise", "pair": "Q7→M7", "score": 0.56},
        {"persona": "Concise", "pair": "L8→M7", "score": 0.62},
        {"persona": "Concise", "pair": "M7→L8", "score": 0.58},
    ]
    df = pd.DataFrame(data)
    order = ["Honest", "Silly", "Concise", "Verbose", "Rude"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    sns.boxplot(
        data=df, x="persona", y="score", hue="persona", order=order,
        palette=PALETTE, width=0.45, linewidth=1.2,
        fliersize=0, saturation=0.75, legend=False, ax=ax,
    )
    sns.stripplot(
        data=df, x="persona", y="score", hue="persona", order=order,
        palette=PALETTE, size=6, jitter=0.15, linewidth=0.5,
        edgecolor="white", legend=False, alpha=0.8, ax=ax,
    )
    ax.set_xlabel("Persona")
    ax.set_ylabel("Trait-match Score")

    ax.set_ylim(0.35, 0.95)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
    ax.axhline(0.5, ls="--", lw=0.7, color="grey", alpha=0.5)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_4_1.png")
    fig.savefig(f"{OUT}/fig_4_1.pdf")
    plt.close(fig)
    print("  ✓ Figure 4.1 saved")


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 4.2 — Cross-Model Transfer Matrix (annotated heatmap)
# ═══════════════════════════════════════════════════════════════════════════════
def fig_4_2():
    models = ["Qwen3B", "Qwen7B", "Llama8B", "Mistral7B"]
    n = len(models)

    # Full 4x4 trait score matrix (diagonal = NaN)
    trait_mat = np.array([
        [np.nan, 0.73, 0.49, 0.55],  # Qwen3B ->
        [0.71, np.nan, 0.47, 0.53],   # Qwen7B ->
        [0.45, 0.48, np.nan, 0.61],   # Llama8B ->
        [0.52, 0.56, 0.58, np.nan],   # Mistral7B ->
    ])

    # Full 4x4 perplexity increase matrix
    ppl_mat = np.array([
        [np.nan, 12.9, 34.2, 27.8],
        [13.8, np.nan, 36.2, 29.4],
        [37.1, 33.5, np.nan, 20.8],
        [29.7, 26.9, 22.6, np.nan],
    ])

    # Annotation strings: trait score + perplexity
    annot = np.empty((n, n), dtype=object)
    for i in range(n):
        for j in range(n):
            if i == j:
                annot[i, j] = "—"
            else:
                annot[i, j] = f"{trait_mat[i,j]:.2f}\n(ppl {ppl_mat[i,j]:.0f})"

    fig, ax = plt.subplots(figsize=(6.5, 5))
    cmap = LinearSegmentedColormap.from_list("teal", ["#f7fcf5", "#238b45"])
    mask = np.eye(n, dtype=bool)
    sns.heatmap(
        trait_mat, annot=annot, fmt="", mask=mask,
        xticklabels=models, yticklabels=models,
        cmap=cmap, vmin=0.4, vmax=0.8, linewidths=1.5,
        linecolor="white", cbar_kws={"label": "Trait-match Score"},
        ax=ax,
    )
    # Grey-out diagonal
    for i in range(n):
        ax.add_patch(plt.Rectangle((i, i), 1, 1, fill=True, color="#e0e0e0", zorder=2))
        ax.text(i + 0.5, i + 0.5, "—", ha="center", va="center",
                fontsize=11, color="#999", zorder=3)
    ax.set_xlabel("Target Model")
    ax.set_ylabel("Source Model")

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_4_2.png")
    fig.savefig(f"{OUT}/fig_4_2.pdf")
    plt.close(fig)
    print("  ✓ Figure 4.2 saved")


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 4.3 — Scaling Mismatch Sweep (dual-axis tradeoff curve)
# ═══════════════════════════════════════════════════════════════════════════════
def fig_4_3():
    data = [
        {"alpha": a / 10, "trait": t, "ppl": p}
        for a, t, p in [
            (1, 0.17, 5), (2, 0.26, 7), (3, 0.33, 8), (4, 0.39, 10),
            (5, 0.45, 12), (6, 0.50, 14), (7, 0.54, 16), (8, 0.57, 18),
            (9, 0.60, 20), (10, 0.61, 23), (11, 0.64, 27), (12, 0.66, 31),
            (13, 0.67, 35), (14, 0.67, 40), (15, 0.67, 46), (16, 0.66, 53),
            (17, 0.65, 60), (18, 0.64, 66), (19, 0.62, 72), (20, 0.60, 78),
        ]
    ]
    df = pd.DataFrame(data)

    fig, ax1 = plt.subplots(figsize=(7, 4.5))
    ax2 = ax1.twinx()

    c1, c2 = "#4C72B0", "#C44E52"
    ax1.plot(df.alpha, df.trait, "-o", color=c1, markersize=5, lw=2, label="Trait-match")
    ax2.plot(df.alpha, df.ppl, "-s", color=c2, markersize=5, lw=2, label="Perplexity")

    # Shade optimal zone
    best = df.loc[df.trait.idxmax(), "alpha"]
    ax1.axvspan(best - 0.15, best + 0.15, color="#55A868", alpha=0.12, label="Sweet spot")
    ax1.axvline(best, ls=":", color="#55A868", lw=1)

    ax1.set_xlabel("Scaling coefficient α")
    ax1.set_ylabel("Trait-match Score", color=c1)
    ax2.set_ylabel("Perplexity Increase (%)", color=c2)
    ax1.tick_params(axis="y", labelcolor=c1)
    ax2.tick_params(axis="y", labelcolor=c2)

    # Merge legends
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", framealpha=0.9)


    ax2.spines["top"].set_visible(False)
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_4_3.png")
    fig.savefig(f"{OUT}/fig_4_3.pdf")
    plt.close(fig)
    print("  ✓ Figure 4.3 saved")


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 4.4 — Basis Alignment (slope graph)
# ═══════════════════════════════════════════════════════════════════════════════
def fig_4_4():
    data = [
        {"pair": "Q7→L8", "before": 0.11, "after": 0.56},
        {"pair": "Q7→M7", "before": 0.15, "after": 0.60},
        {"pair": "L8→M7", "before": 0.18, "after": 0.62},
        {"pair": "M7→L8", "before": 0.13, "after": 0.55},
        {"pair": "Q3→Q7", "before": 0.27, "after": 0.59},
        {"pair": "Q7→Q3", "before": 0.24, "after": 0.57},
        {"pair": "Q3→L8", "before": 0.12, "after": 0.54},
        {"pair": "Q3→M7", "before": 0.14, "after": 0.58},
    ]
    df = pd.DataFrame(data)

    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    colors = plt.cm.Set2(np.linspace(0, 0.9, len(df)))

    for i, row in df.iterrows():
        ax.plot([0, 1], [row.before, row.after], "-o", color=colors[i],
                lw=2, markersize=8, markeredgecolor="white", markeredgewidth=1,
                label=row.pair)

    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Before\nAlignment", "After\nAlignment"], fontsize=11)
    ax.set_xlim(-0.1, 1.1)
    ax.set_ylim(0.0, 0.72)
    ax.set_ylabel("Cosine Similarity")
    ax.legend(title="Transfer Pair", loc="upper center",
              bbox_to_anchor=(0.5, -0.12), ncol=4, framealpha=0.9, fontsize=9)

    ax.spines["bottom"].set_visible(False)
    ax.tick_params(bottom=False)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_4_4.png")
    fig.savefig(f"{OUT}/fig_4_4.pdf")
    plt.close(fig)
    print("  ✓ Figure 4.4 saved")


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 4.5 — Layer Sweep (smooth area curve)
# ═══════════════════════════════════════════════════════════════════════════════
def fig_4_5():
    data = [
        {"layer": l, "trait": t}
        for l, t in [
            (1, 0.21), (2, 0.28), (3, 0.31), (4, 0.35), (5, 0.39),
            (6, 0.44), (7, 0.48), (8, 0.53), (9, 0.57), (10, 0.61),
            (11, 0.65), (12, 0.69), (13, 0.72), (14, 0.75), (15, 0.78),
            (16, 0.80), (17, 0.82), (18, 0.83), (19, 0.82), (20, 0.81),
            (21, 0.79), (22, 0.76), (23, 0.73), (24, 0.69), (25, 0.65),
            (26, 0.60), (27, 0.56), (28, 0.52),
        ]
    ]
    df = pd.DataFrame(data)

    # Smooth spline
    x = df.layer.values
    y = df.trait.values
    xnew = np.linspace(x.min(), x.max(), 300)
    spl = make_interp_spline(x, y, k=3)
    ynew = spl(xnew)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.fill_between(xnew, 0, ynew, alpha=0.18, color="#4C72B0")
    ax.plot(xnew, ynew, lw=2.2, color="#4C72B0")
    ax.scatter(x, y, s=25, color="#4C72B0", zorder=5, edgecolor="white", linewidth=0.5)

    # Mark peak
    peak_idx = np.argmax(y)
    ax.annotate(
        f"Peak: layer {x[peak_idx]} ({y[peak_idx]:.2f})",
        xy=(x[peak_idx], y[peak_idx]),
        xytext=(x[peak_idx] + 3, y[peak_idx] + 0.04),
        arrowprops=dict(arrowstyle="->", color="#333", lw=1),
        fontsize=10, color="#333",
    )

    ax.set_xlabel("Layer Index")
    ax.set_ylabel("Trait-match Score")

    ax.set_ylim(0, 0.95)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(2))
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_4_5.png")
    fig.savefig(f"{OUT}/fig_4_5.pdf")
    plt.close(fig)
    print("  ✓ Figure 4.5 saved")


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 4.6 — Null Hypothesis Evaluation (boxplot + jitter)
# ═══════════════════════════════════════════════════════════════════════════════
def fig_4_6():
    data = [
        {"condition": "Raw", "run": i, "trait": t}
        for i, t in enumerate([0.60, 0.63, 0.59, 0.61, 0.62, 0.60, 0.64, 0.58, 0.61, 0.62], 1)
    ] + [
        {"condition": "Random", "run": i, "trait": t}
        for i, t in enumerate([0.22, 0.27, 0.25, 0.21, 0.23, 0.24, 0.26, 0.20, 0.24, 0.25], 1)
    ] + [
        {"condition": "Permuted", "run": i, "trait": t}
        for i, t in enumerate([0.19, 0.22, 0.24, 0.20, 0.23, 0.21, 0.18, 0.22, 0.20, 0.21], 1)
    ] + [
        {"condition": "Corrected", "run": i, "trait": t}
        for i, t in enumerate([0.87, 0.89, 0.90, 0.86, 0.88, 0.89, 0.87, 0.91, 0.88, 0.89], 1)
    ]
    df = pd.DataFrame(data)
    order = ["Permuted", "Random", "Raw", "Corrected"]
    colors = ["#999999", "#8172B3", "#4C72B0", "#55A868"]

    fig, ax = plt.subplots(figsize=(6.5, 4.5))
    sns.boxplot(
        data=df, x="condition", y="trait", hue="condition", order=order,
        palette=colors, width=0.45, linewidth=1.2,
        fliersize=0, saturation=0.75, legend=False, ax=ax,
    )
    sns.stripplot(
        data=df, x="condition", y="trait", order=order,
        color="black", size=4.5, jitter=0.15, alpha=0.6, ax=ax,
    )

    # Significance bracket between Permuted and Corrected
    y_top = 0.96
    ax.plot([0, 0, 3, 3], [y_top - 0.01, y_top, y_top, y_top - 0.01],
            lw=1, color="black")
    ax.text(1.5, y_top + 0.005, "***  p < 0.001", ha="center", va="bottom", fontsize=9)

    ax.set_xlabel("Condition")
    ax.set_ylabel("Trait-match Score")

    ax.set_ylim(0.10, 1.02)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_4_6.png")
    fig.savefig(f"{OUT}/fig_4_6.pdf")
    plt.close(fig)
    print("  ✓ Figure 4.6 saved")


# ═══════════════════════════════════════════════════════════════════════════════
# Figure 4.7 — Correction Pipeline (connected-dot progression)
# ═══════════════════════════════════════════════════════════════════════════════
def fig_4_7():
    data = [
        {"pair": "Q7→L8", "raw": 0.47, "scale": 0.58, "basis": 0.72, "layer": 0.79, "final": 0.88},
        {"pair": "Q7→M7", "raw": 0.53, "scale": 0.63, "basis": 0.76, "layer": 0.82, "final": 0.89},
        {"pair": "L8→M7", "raw": 0.61, "scale": 0.69, "basis": 0.80, "layer": 0.85, "final": 0.90},
        {"pair": "M7→L8", "raw": 0.58, "scale": 0.67, "basis": 0.78, "layer": 0.83, "final": 0.88},
        {"pair": "Q3→Q7", "raw": 0.73, "scale": 0.78, "basis": 0.84, "layer": 0.87, "final": 0.91},
        {"pair": "Q7→Q3", "raw": 0.71, "scale": 0.77, "basis": 0.83, "layer": 0.86, "final": 0.90},
    ]
    df = pd.DataFrame(data)
    stages = ["raw", "scale", "basis", "layer", "final"]
    stage_labels = ["Raw\nTransfer", "Scale\nCorrection", "Basis\nAlignment", "Layer\nSelection", "Final\nPipeline"]

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = plt.cm.Set2(np.linspace(0, 0.85, len(df)))

    for i, row in df.iterrows():
        vals = [row[s] for s in stages]
        ax.plot(range(len(stages)), vals, "-o", color=colors[i], lw=2,
                markersize=7, markeredgecolor="white", markeredgewidth=0.8,
                label=row.pair, zorder=3)

    ax.set_xticks(range(len(stages)))
    ax.set_xticklabels(stage_labels, fontsize=10)
    ax.set_ylabel("Trait-match Score")

    ax.set_ylim(0.40, 0.96)
    ax.yaxis.set_major_formatter(ticker.FormatStrFormatter("%.2f"))
    ax.legend(loc="lower right", ncol=2, framealpha=0.9, title="Transfer Pair")

    # Light grid for readability
    ax.yaxis.grid(True, ls="--", alpha=0.3)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(f"{OUT}/fig_4_7.png")
    fig.savefig(f"{OUT}/fig_4_7.pdf")
    plt.close(fig)
    print("  ✓ Figure 4.7 saved")


# ── Run all ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Generating figures …")
    fig_4_1()
    fig_4_2()
    fig_4_3()
    fig_4_4()
    fig_4_5()
    fig_4_6()
    fig_4_7()
    print("Done — all figures saved to", OUT)
