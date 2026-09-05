"""Check logged prompt privacy, independent histories, and exported AWS artifact."""
import argparse
import json
from pathlib import Path

from inspect_ai.log import read_eval_log

from collaboration_prompt import COLLABORATION_NOTE

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    prompts = json.loads((directory / "prompts.json").read_text())
    log = read_eval_log(manifest["logs"][0], resolve_attachments=True)
    sample = log.samples[0]
    spans = {e.id:e.name for e in sample.events if e.event == "span_begin" and e.type == "agent"}
    models = [e for e in sample.events if e.event == "model"]
    owners = {}
    histories = {name:json.loads((directory / (name + ".json")).read_text()) for name in prompts}
    for name, history in histories.items():
        for message in history["messages"]:
            for call in message.get("tool_calls") or []:
                owners[call["id"]] = name
    checks = {"expected_agent_spans": sorted(spans.values()) == sorted(prompts)}
    for sid, name in spans.items():
        calls = [m for m in models if m.span_id == sid]
        first = calls[0].input
        checks[name + "_exact_initial_prompt"] = len(first) == 1 and first[0].role == "user" and first[0].text == prompts[name]
        checks[name + "_only_own_identity"] = not any(other in first[0].text for other in prompts if other != name)
        checks[name + "_collaboration_note"] = first[0].text.endswith(COLLABORATION_NOTE)
        checks[name + "_independent_tool_history"] = all(owners.get(m.tool_call_id) == name for e in calls for m in e.input if m.role == "tool")
    config = json.loads((directory / "container.json").read_text())[0]
    checks["network_none"] = config["HostConfig"]["NetworkMode"] == "none"
    checks["no_host_mounts"] = not config["Mounts"]
    checks["text_demo_image"] = config["Config"]["Image"].startswith("python:3.12-slim@sha256:")
    checks["ssh_remote_context"] = manifest["endpoint"].startswith("ssh://")
    checks["scored_exported_file"] = sample.output.completion == (directory / "workspace/names.txt").read_text()
    timeline=[]
    for e in models:
        if e.completed:
            timeline.extend([(e.timestamp,1),(e.completed,-1)])
    active=peak=0
    for _,delta in sorted(timeline):
        active += delta
        peak=max(peak,active)
    report = {"infrastructure_checks": checks, "all_infrastructure_checks_passed": all(checks.values()),
              "agent_count":len(spans), "model_calls":len(models), "peak_logged_inflight_model_calls":peak,
              "model_calls_by_agent": {name:sum(e.span_id == sid for e in models) for sid,name in spans.items()},
              "compactions":sum(e.event == "compaction" for e in sample.events),
              "team_result":json.loads((directory / "result.json").read_text())["checks"]}
    (directory / "verification.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    assert all(checks.values())

if __name__ == "__main__":
    main()
