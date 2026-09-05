"""Flatten an inspect eval_set log dir into one jsonl row per rollout.
uv run -m src.experiments.sandbagging.extract --log_dir logs/sweep_v3 --output_path results/sweep_v3.jsonl
"""

import argparse
import json
import logging
import subprocess
from pathlib import Path

from inspect_ai.log import list_eval_logs, read_eval_log

LOGGER = logging.getLogger(__name__)


def git_hash() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()[:8]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--log_dir", required=True)
    p.add_argument("--output_path", required=True)
    p.add_argument("--include_incomplete", action="store_true",
                   help="keep scored samples from error/started logs; per cell, the log with most")
    a = p.parse_args()

    out = Path(a.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(out.parent / "run.log")])

    # one log per cell: a resumed run leaves several, so keep whichever scored the most
    best = {}
    for f in list_eval_logs(a.log_dir):
        log = read_eval_log(f.name)
        if log.status != "success" and not a.include_incomplete:
            LOGGER.warning(f"skipping incomplete task {log.eval.task} status={log.status}")
            continue
        scored = [s for s in (log.samples or []) if s.scores]
        if len(scored) <= len(best.get(log.eval.task, (None, []))[1]):
            continue
        if log.status != "success":
            LOGGER.warning(f"including {log.eval.task} status={log.status} "
                           f"scored={len(scored)}/{len(log.samples or [])}")
        best[log.eval.task] = (log, scored)

    rows, models = [], set()
    for log, scored in best.values():
        models.add(log.eval.model)
        for s in scored:
            acc = s.scores["arithmetic_accuracy"]
            judge = s.scores.get("sandbagging_intent")
            rows.append({
                "id": f"{log.eval.task}_{s.id}",
                "cell": log.eval.task,
                "framing": s.metadata["framing"],
                "threshold": s.metadata["threshold"],
                "direction": s.metadata["direction"],
                "seed": s.metadata["seed"],
                "accuracy": round(acc.value["accuracy"], 4),
                "refused": bool(acc.value["refused"]),
                "n_correct": acc.metadata["n_correct"],
                "n_answered": acc.metadata["n_answered"],
                "share_option_a": round(acc.metadata["share_option_a"], 4),
                "answers": acc.answer,
                "answer_key": acc.metadata["answer_key"],
                "judge": judge.value if judge else None,
            })

    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    cfg = out.with_suffix(".config.json")
    cfg.write_text(json.dumps({"git_hash": git_hash(), "log_dir": a.log_dir,
                               "models": sorted(models), "n_rollouts": len(rows),
                               "include_incomplete": a.include_incomplete,
                               "n_per_cell": {c: sum(r["cell"] == c for r in rows)
                                              for c in sorted({r["cell"] for r in rows})}}, indent=2))
    print(f"wrote {out} ({len(rows)} rollouts)")
    print(f"wrote {cfg}")
    print(f"Plot with: uv run -m src.experiments.sandbagging.plot {out}")


if __name__ == "__main__":
    main()
