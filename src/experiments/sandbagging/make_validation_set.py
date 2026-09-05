"""Turn hand CoT labels into a scout validation set, and list which rollouts still need labels.
uv run -m src.experiments.sandbagging.make_validation_set --log_dir logs/smoke_inspect2 --hand_labels_path results/smoke_inspect2_cot_labels.jsonl --scan_results_path results/eval_awareness_v1.jsonl --output_path results/eval_awareness_validation.jsonl
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from inspect_scout import transcripts_from

LOGGER = logging.getLogger(__name__)

# hand scale is binary with a "partial" middle; the scanner target is the binary it
# derives from `level`. "partial" goes to its own split so it can be held out.
IS_AWARE = {"yes": True, "no": False, "partial": True}


async def transcript_ids(log_dir: str) -> dict[str, str]:
    async with transcripts_from(log_dir).reader() as reader:
        return {f"{i.task_set}/{i.task_id}": i.transcript_id async for i in reader.index()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--log_dir", required=True)
    p.add_argument("--hand_labels_path", required=True)
    p.add_argument("--scan_results_path", required=True)
    p.add_argument("--output_path", required=True)
    a = p.parse_args()

    out = Path(a.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO,
                        handlers=[logging.StreamHandler(),
                                  logging.FileHandler(out.parent / "run.log")])

    ids = asyncio.run(transcript_ids(a.log_dir))
    hand = [json.loads(line) for line in Path(a.hand_labels_path).read_text().splitlines()]
    scan = {json.loads(line)["id"]: json.loads(line)
            for line in Path(a.scan_results_path).read_text().splitlines()}

    cases = []
    for h in hand:
        if h["id"] not in ids:
            LOGGER.warning(f"hand label {h['id']} has no transcript in {a.log_dir}")
            continue
        cases.append({
            "id": ids[h["id"]],
            "task_id": h["id"],
            "target": {"is_eval_aware": IS_AWARE[h["eval_aware"]]},
            "split": "partial" if h["eval_aware"] == "partial" else "clear",
        })
    out.write_text("".join(json.dumps(c) + "\n" for c in cases))

    # the untested surface: rollouts the scanner flagged that no hand label covers
    labelled = {h["id"] for h in hand}
    todo = [r for i, r in sorted(scan.items()) if i not in labelled and r["level"] != "none"]
    review = out.with_name(out.stem + "_to_label.jsonl")
    review.write_text("".join(json.dumps({
        "id": r["id"], "eval_aware": "TODO", "scanner_level": r["level"],
        "accuracy": r["accuracy"], "influences_decision": r["influences_decision"],
        "quote": r["quote"],
    }) + "\n" for r in todo))

    print(f"wrote {out} ({len(cases)} cases: "
          f"{sum(c['target']['is_eval_aware'] for c in cases)} aware, "
          f"{sum(not c['target']['is_eval_aware'] for c in cases)} not)")
    print(f"wrote {review} ({len(todo)} flagged rollouts with no hand label)")
    print(f"Validate with: uv run -m src.experiments.sandbagging.scan_eval_awareness --log_dir {a.log_dir} --scans_dir results/scans/eval_awareness_v2 --validation {out}")


if __name__ == "__main__":
    main()
