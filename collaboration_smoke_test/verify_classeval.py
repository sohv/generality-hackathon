"""Audit the actual completed log, independently of participant claims."""
import argparse
import hashlib
import json
from pathlib import Path

from inspect_ai.log import read_eval_log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    directory = args.run_directory.resolve()
    # Compare with the exact prompts saved for this run, including historical
    # unaware runs, rather than today's default condition.
    PROMPT = (directory / "prompt.txt").read_text()
    SYSTEM = (directory / "system.txt").read_text()
    manifest = json.loads((directory / "manifest.json").read_text())
    log = read_eval_log(manifest["logs"][0], resolve_attachments=True)
    sample = log.samples[0]
    models = [e for e in sample.events if e.event == "model"]
    spans = {e.id: e.name for e in sample.events if e.event == "span_begin" and e.type == "agent"}
    team = json.loads((directory / "team.json").read_text())
    histories = {}
    for span_id, label in spans.items():
        path = directory / f"{label}.json"
        if not path.exists():
            events = [e for e in models if e.span_id == span_id]
            last = events[-1]
            recovered = {"messages": [m.model_dump(mode="json") for m in last.input],
                         "output": last.output.model_dump(mode="json"),
                         "submitted": label in team.get("submissions", {}), "limit": None,
                         "error": team.get("agents", {}).get(label, {}).get("error"),
                         "reconstructed_from_eval": True}
            path.write_text(json.dumps(recovered, indent=2))
        histories[label] = json.loads(path.read_text())
    tool_owner = {}
    for label, history in histories.items():
        for msg in history["messages"]:
            for call in msg.get("tool_calls") or []:
                tool_owner[call["id"]] = label
    checks, per_agent = {}, {}
    for span_id, label in spans.items():
        events = [e for e in models if e.span_id == span_id]
        if not events:
            checks[f"{label}_model_calls_exist"] = False
            continue
        first = events[0]
        checks[f"{label}_verbatim_initial_messages"] = (
            len(first.input) == 2 and first.input[0].role == "system" and first.input[0].text == SYSTEM
            and first.input[1].role == "user" and first.input[1].text == PROMPT)
        checks[f"{label}_private_tool_history"] = all(
            tool_owner.get(m.tool_call_id) == label
            for e in events for m in e.input if m.role == "tool")
        checks[f"{label}_no_added_user_instructions"] = all(
            m.text == PROMPT for e in events for m in e.input if m.role == "user")
        tools_text = json.dumps([t.model_dump(mode="json") for t in first.tools]).lower()
        checks[f"{label}_neutral_tools"] = not any(word in tools_text for word in ["collaborat", "teammate", "agent_", "peer", "shared"])
        per_agent[label] = {"model_calls": len(events), "submitted": histories[label]["submitted"],
                            "limit": histories[label]["limit"],
                            "retries_field": [e.retries for e in events]}
    checks["three_agent_spans"] = sorted(spans.values()) == sorted(histories)
    audit = [json.loads(s) for s in (directory / "audit.jsonl").read_text().splitlines()]
    starts = [e for e in audit if e["event"] == "agent_start"]
    checks["same_container"] = len(starts) == 3 and {e["container"] for e in starts} == {team["container"]}
    frozen = (directory / "final_solution.py").read_bytes()
    checks["workspace_matches_frozen_file"] = frozen == (directory / "workspace/solution.py").read_bytes()
    checks["scored_frozen_file"] = sample.output.completion.encode() == frozen
    summary = {"checks": checks, "per_agent": per_agent,
               "final_sha256": hashlib.sha256(frozen).hexdigest(),
               "model_usage": {k:v.model_dump(mode="json") for k,v in log.stats.model_usage.items()},
               "compactions": sum(e.event == "compaction" for e in sample.events),
               "result": json.loads((directory / "result.json").read_text())}
    (directory / "verification.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if not all(checks.values()):
        raise SystemExit("One or more audit checks failed")

if __name__ == "__main__":
    main()
