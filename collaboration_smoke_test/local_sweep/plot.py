"""Plot the saved exploratory team-level results; never rerun agents."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    rows = json.loads((args.batch / "summary.json").read_text())
    if not rows:
        return
    x = [r["agents"] for r in rows]
    y = [r["coverage_percent"] for r in rows]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.9), layout="constrained")
    axes[0].plot(x, y, marker="o", color="#2563eb", linewidth=2)
    diagnostics_path = args.batch / "completion_diagnostics.json"
    diagnostics = {r["agents"]: r for r in json.loads(diagnostics_path.read_text())} if diagnostics_path.exists() else {}
    limited = [r for r in rows if diagnostics.get(r["agents"], {}).get("submitted", r["agents"]) < r["agents"]]
    paused = [r for r in rows if diagnostics.get(r["agents"], {}).get("operator_pause_timeout", 0)]
    if limited:
        axes[0].scatter([r["agents"] for r in limited], [r["coverage_percent"] for r in limited],
                        marker="s", s=50, color="#d97706", zorder=3, label="Includes limit/error stops")
    if paused:
        axes[0].scatter([r["agents"] for r in paused], [r["coverage_percent"] for r in paused],
                        marker="x", s=80, linewidths=2, color="#dc2626", zorder=4, label="Operator pause caused timeouts")
    if limited or paused:
        axes[0].legend(loc="lower left", fontsize=7)
    for r in rows:
        axes[0].annotate(f"{r['coverage_percent']:.1f}%", (r["agents"], r["coverage_percent"]),
                         xytext=(0, 8), textcoords="offset points", ha="center", fontsize=8)
    axes[0].set(ylim=(-3, 110), ylabel="Expected names present (%)", title="Final shared-file coverage")
    axes[1].plot(x, [r["seconds"]/60 for r in rows], marker="o", color="#0f766e", linewidth=2)
    axes[1].set(ylabel="Elapsed minutes", title="Team runtime (includes API queueing)")
    for ax in axes:
        ax.set_xscale("log", base=2)
        ax.set_xticks([2**i for i in range(1,11)])
        ax.xaxis.set_major_formatter(ScalarFormatter())
        ax.tick_params(axis="x", labelrotation=45)
        ax.set_xlabel("Agents sharing one workspace")
        ax.grid(alpha=.2)
    total = sum(r["logged_cost_usd"] for r in rows)
    fig.suptitle(f"Local names sweep · one team attempt per size · GLM 5.3 Flash\n"
                 f"128 API slots divided across concurrent teams · completed-team model cost ${total:.4f}", fontsize=12)
    fig.savefig(args.batch / "scaling.png", dpi=180)
    fig.savefig(args.batch / "scaling.svg")
    fig.savefig(args.batch / "scaling.pdf")
    plt.close(fig)
    histories, ax = plt.subplots(figsize=(9, 5.2), layout="constrained")
    for r in rows:
        n = r["agents"]
        path = args.batch / f"n{n:04d}" / f"n{n:04d}" / "coverage_timeline.csv"
        if not path.exists():
            continue
        with path.open() as stream:
            events = list(csv.DictReader(stream))
        if events:
            ax.step([float(e["seconds_from_first_tool"])/60 for e in events],
                    [float(e["coverage_percent"]) for e in events], where="post", linewidth=1.2, label=str(n))
    ax.set(xlabel="Minutes since team's first file-tool event", ylabel="Expected names present (%)",
           ylim=(-3, 105), title="Shared names.txt coverage after each successful write\nDownward steps mean a write removed expected names")
    ax.grid(alpha=.2)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels, title="Agents", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    histories.savefig(args.batch / "coverage_history.png", dpi=180)
    histories.savefig(args.batch / "coverage_history.svg")
    plt.close(histories)
    (args.batch / "plot_metadata.json").write_text(json.dumps({"matplotlib": matplotlib.__version__,
            "note": "Exploratory single-repetition results; no uncertainty estimates or power-law fit."},indent=2))
    print(args.batch / "scaling.png")


if __name__ == "__main__":
    main()
