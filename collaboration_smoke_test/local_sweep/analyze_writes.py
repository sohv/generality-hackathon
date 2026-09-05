"""Reconstruct names-file coverage changes from completed local audit writes."""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.batch / "manifest.json").read_text())
    summary = []
    for directory in sorted(args.batch.glob("n[0-9][0-9][0-9][0-9]")):
        if not (directory / "result.json").exists():
            continue
        roster = set(json.loads((directory / "prompts.json").read_text()))
        previous = set()
        drops = losses = writes = maximum = 0
        first = None
        with (directory / "coverage_timeline.csv").open("w", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=["time", "seconds_from_first_tool", "agent", "correct_count",
                                                     "coverage_percent", "names_added", "names_removed"])
            writer.writeheader()
            with (directory / "audit.jsonl").open() as stream:
                for line in stream:
                    event = json.loads(line)
                    timestamp = datetime.fromisoformat(event["time"])
                    if first is None:
                        first = timestamp
                    op = event["operation"]
                    if op.get("op") != "write" or op.get("name") != "names.txt" or event.get("error"):
                        continue
                    current = {name.strip() for name in op["text"].splitlines()} & roster
                    lost, added = len(previous-current), len(current-previous)
                    writes += 1
                    maximum = max(maximum, len(current))
                    drops += bool(lost)
                    losses += lost
                    writer.writerow({"time": event["time"], "seconds_from_first_tool": (timestamp-first).total_seconds(),
                                     "agent": event["agent"], "correct_count": len(current),
                                     "coverage_percent": 100*len(current)/len(roster),
                                     "names_added": added, "names_removed": lost})
                    previous = current
        summary.append({"agents": len(roster), "names_file_writes": writes,
                        "writes_removing_expected_names": drops, "expected_name_removals": losses,
                        "maximum_names_after_a_write": maximum, "names_after_last_write": len(previous)})
    (args.batch / "write_analysis.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
