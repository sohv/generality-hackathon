"""Pilot figure: per-rollout accuracy by condition.

Form choice: a strip plot of every rollout, not a bar chart of means. The central
pilot finding is that the disambiguated cell is *bimodal* -- a mixture of "resist
entirely" and "target the threshold" -- and a bar of means would hide exactly that.
"""
import json, random
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
R = ROOT / "results"
OUT = ROOT / "results" / "figures" / "fig_pilot.png"

# Categorical slots 1-3 of the validated default palette (all-pairs clean).
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8880"
SURFACE = "#fcfcfb"

COLS = [
    ("pilot_sonnet4.jsonl",      "control",        "Control\n(no document)", BLUE,   0),
    ("pilot_sonnet4.jsonl",      "ambiguous_T50",  "Ambiguous\nT = 50%",     ORANGE, 1),
    ("pilot_goal_sonnet4.jsonl", "control",        "Control\n(no document)", BLUE,   2.9),
    ("pilot_goal_sonnet4.jsonl", "ambiguous_T50",  "Ambiguous\nT = 50%",     ORANGE, 3.9),
    ("pilot_goal_sonnet4.jsonl", "disambig_T50",   "Disambiguated\nT = 50%", AQUA,   4.9),
]


def load(fn, cell):
    rows = [json.loads(l) for l in (R / fn).open()]
    return [r["accuracy"] for r in rows if "error" not in r and r["cell"] == cell]


def boot(xs, n=20000, seed=0):
    rng = random.Random(seed)
    ms = sorted(mean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return ms[int(0.005 * n)], ms[int(0.995 * n)]


fig, ax = plt.subplots(figsize=(9.2, 5.4))
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

# Reference lines, recessive and behind the marks.
ax.axhline(1.0, ls=(0, (5, 4)), lw=1, color=MUTED, zorder=1)
ax.axhline(0.5, ls=(0, (5, 4)), lw=1, color=MUTED, zorder=1)
ax.text(5.95, 1.012, "honest baseline", va="bottom", ha="right", fontsize=8.5, color=INK2)
ax.text(5.95, 0.512, "leaked threshold T = 50%", va="bottom", ha="right", fontsize=8.5, color=INK2)

rng = random.Random(11)
for fn, cell, label, colour, x in COLS:
    ys = load(fn, cell)
    lo, hi = boot(ys)
    m = mean(ys)
    # every rollout, jittered; 2px surface ring so overlapping points stay countable
    ax.scatter([x + rng.uniform(-0.13, 0.13) for _ in ys], ys, s=52, color=colour,
               edgecolor=SURFACE, linewidth=1.6, alpha=0.9, zorder=3)
    # mean + bootstrap 99% CI in ink, never in the series colour
    ax.plot([x - 0.26, x + 0.26], [m, m], lw=2.2, color=INK, zorder=4)
    ax.plot([x, x], [lo, hi], lw=1.4, color=INK, zorder=4)
    # direct label on every column (relief rule: aqua is below 3:1 on this surface)
    ax.annotate(f"{m:.0%}", (x + 0.28, m), textcoords="offset points", xytext=(4, -4),
                ha="left", fontsize=10.5, color=INK, zorder=5)

ax.axvline(2.45, lw=1, color="#e2e1dc", zorder=0)
for cx, txt, sub in [(0.5, "Plain system prompt", "no goal given"),
                     (3.9, "Apollo goal system prompt", '"nothing else matters"')]:
    ax.text(cx, 1.205, txt, ha="center", fontsize=11, color=INK, fontweight="bold")
    ax.text(cx, 1.155, sub, ha="center", fontsize=9, color=INK2, style="italic")

ax.set_xticks([c[4] for c in COLS])
ax.set_xticklabels([c[2] for c in COLS], fontsize=9.5, color=INK2)
ax.set_xlim(-0.5, 5.95)
ax.set_ylim(0.24, 1.28)
ax.set_yticks([0.25, 0.5, 0.75, 1.0])
ax.set_yticklabels(["25%", "50%", "75%", "100%"], fontsize=9.5, color=INK2)
ax.set_ylabel("Achieved accuracy (one point = one rollout)", fontsize=10.5, color=INK2)
ax.yaxis.grid(True, color="#eceae4", lw=0.9)
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color("#d8d6cf")
ax.tick_params(length=0)

fig.tight_layout(rect=(0, 0.01, 1, 0.99))
fig.savefig(OUT, dpi=220, facecolor=SURFACE)
print("wrote", OUT)
