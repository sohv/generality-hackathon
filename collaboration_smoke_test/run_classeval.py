"""Run one three-agent ClassEval pilot with the hackathon GLM key only."""
import fcntl
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone

from dotenv import dotenv_values
from inspect_ai import eval
from inspect_ai.model import ModelCost

from smoke_team import ROOT, MODEL
from run_smoke import api, key_usage
from classeval_team import BASE, IMAGE, RECORD, PROMPT, SYSTEM, ORIGINAL_PROMPT, classeval_shared, evaluate_code

def main():
    key = dotenv_values(ROOT / ".env").get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Hackathon key missing")
    os.environ["OPENROUTER_API_KEY"] = key
    lock = (ROOT / ".smoke-budget.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    pricing = next(m for m in api("models")["data"] if m["id"] == "z-ai/glm-5.3-flash")
    before = key_usage()
    if before["limit_remaining"] is None or before["limit_remaining"] < .5:
        raise RuntimeError("Insufficient allowance for $0.50 reservation")
    if float(pricing["pricing"]["prompt"]) > .075 / 1e6 or float(pricing["pricing"]["completion"]) > .25 / 1e6:
        raise RuntimeError("Model exceeds declared price ceiling")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = BASE / "runs" / stamp
    workspace = directory / "workspace"
    workspace.mkdir(parents=True)
    (directory / "source").mkdir()
    for filename in ("classeval_team.py", "run_classeval.py", "collaboration_prompt.py"):
        shutil.copy2(ROOT / filename, directory / "source" / filename)
    (workspace / "solution.py").write_text(RECORD["skeleton"])
    (directory / "prompt.txt").write_text(PROMPT)
    (directory / "system.txt").write_text(SYSTEM)
    os.environ.update(CLASSEVAL_RUN_DIR=str(directory), TEAM_WORKSPACE_PATH=str(workspace))
    manifest = {"status": "validating", "model": MODEL, "requested_agents": 3,
                "dataset_revision": "fef204b34e221f207f47904ee660bb920d4c5d1d",
                "inspect_evals_commit": "ac481c7a7b4fb05d6befdfea59b47fc61b839a4f",
                "task_id": RECORD["task_id"], "selection": "ExpressionCalculator chosen before model execution for its six dependent methods; not a random sample or difficulty estimate.",
                "image": IMAGE, "workspace": str(workspace), "reserved_usd": .5,
                "key_usage_before": before, "pricing_snapshot": pricing,
                "limits": {"team_cost_stop_usd": .10, "team_seconds": 600, "per_agent_tokens": 150000,
                           "per_agent_turns": 12, "max_output_tokens": 32768, "max_connections": 3,
                           "compaction_threshold": .75, "temperature": .5, "seed": None},
                "budget_note": "$0.50 reserved; $0.10 team stop with at most three in-flight calls at provider price ceilings. Retries/compaction usage remain in Inspect logs.",
                "versions": {p: importlib.metadata.version(p) for p in ("inspect-ai", "openai")},
                "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in [ROOT / "classeval_team.py", ROOT / "run_classeval.py", ROOT / "uv.lock",
                                            BASE / "compose.yaml", BASE / "upstream/utils.py", BASE / "upstream/class_eval.py",
                                            BASE / "data/ClassEval_39.json"]},
                "condition": "unaware_shared_workspace" if PROMPT == ORIGINAL_PROMPT else "collaboration_note_count_hidden",
                "system_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
                "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest()}
    manifest["limits"].update(reasoning_effort="low", attempt_timeout=90, per_agent_seconds=300)
    path = directory / "manifest.json"
    def save():
        path.write_text(json.dumps(manifest, indent=2))
    save()
    print(f"Run directory: {directory}\nReserved $0.50; remaining ${before['limit_remaining']:.6f}", flush=True)
    try:
        controls = {"reference": evaluate_code(RECORD["solution_code"]),
                    "unfinished_skeleton": evaluate_code(RECORD["skeleton"])}
        (directory / "scorer_controls.json").write_text(json.dumps(controls, indent=2))
        if controls["reference"]["outcome"] != "pass" or controls["reference"]["tests_run"] == 0 or controls["unfinished_skeleton"]["outcome"] != "fail":
            raise RuntimeError("Scorer control checks failed")
        manifest["status"] = "running"
        save()
        print(f"Scorer controls passed ({controls['reference']['tests_run']} tests); starting three agents ({manifest['condition']}).", flush=True)
        logs = eval(classeval_shared(), model=MODEL, log_dir=str(ROOT), log_realtime=True,
                    log_buffer=1, log_shared=1, display="plain", sandbox_cleanup=True,
                    model_cost_config={MODEL: ModelCost(input=.075, output=.25, input_cache_write=.075, input_cache_read=.015)},
                    metadata={"run_manifest": str(path), "dataset_revision": manifest["dataset_revision"]})
        manifest.update(status=logs[0].status, logs=[l.location for l in logs],
                        log_stats=[l.stats.model_dump(mode="json") for l in logs])
        print(f"Eval: {logs[0].location}", flush=True)
    except BaseException as exc:
        manifest.update(status="error", error=repr(exc))
        raise
    finally:
        try:
            manifest["key_usage_after"] = key_usage()
        except Exception as exc:
            manifest["key_usage_after_error"] = repr(exc)
        manifest["account_delta_note"] = "Other processes may spend from this key. Attribute this run using logged model cost."
        save()

if __name__ == "__main__":
    main()
