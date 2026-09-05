"""Run GLM 5.3 Flash only; write outputs beside this script in collaboration_smoke_test."""

import argparse
import fcntl
import importlib.metadata
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, ModelCost
from inspect_ai.scorer import includes
from inspect_ai.solver import generate

from smoke_team import MODEL, ROOT, collaboration_smoke

RESERVATION_USD = 0.50


def api(path: str, authenticated: bool = False) -> dict:
    headers = {"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"]} if authenticated else {}
    req = urllib.request.Request("https://openrouter.ai/api/v1/" + path, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def key_usage() -> dict:
    data = api("key", authenticated=True)["data"]
    return {k: data.get(k) for k in ("limit", "limit_remaining", "usage", "usage_daily")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", action="store_true", help="Run five agents with private names and no disclosed count")
    args = parser.parse_args()
    key = dotenv_values(ROOT / ".env").get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("Set the hackathon OPENROUTER_API_KEY in the git-ignored .env beside this script")
    os.environ["OPENROUTER_API_KEY"] = key
    # Serialize our own batches so reserved budget cannot be double-spent here.
    lock = (ROOT / ".smoke-budget.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = "smoke-" + stamp
    workspace = ROOT / ("team-workspace-" + stamp)
    workspace.mkdir()
    os.environ.update(TEAM_RUN_ID=run_id, TEAM_WORKSPACE_PATH=str(workspace))
    pricing = next(m for m in api("models")["data"] if m["id"] == "z-ai/glm-5.3-flash")
    before = key_usage()
    if before["limit_remaining"] is None or before["limit_remaining"] < RESERVATION_USD:
        raise RuntimeError("Insufficient verified key allowance to reserve $0.50")
    if float(pricing["pricing"]["prompt"]) > 0.075 / 1e6 or float(pricing["pricing"]["completion"]) > 0.25 / 1e6:
        raise RuntimeError("Model prices exceed this smoke test's predeclared price ceiling")
    metadata = {
        "run_id": run_id, "model": MODEL, "workspace": str(workspace),
        "reserved_usd": RESERVATION_USD, "key_usage_before": before,
        "pricing_snapshot": pricing,
        "versions": {p: importlib.metadata.version(p) for p in ("inspect-ai", "openai")},
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {},
        "budget_note": "Team stop threshold $0.10 plus at most 3 in-flight calls, each capped at model context and 8192 output tokens; max_retries=0. Reserve $0.50 including preflight.",
        "condition": "roster_discovery" if args.discovery else "named_collaboration",
        "status": "running",
    }
    import hashlib
    for filename in ("smoke_team.py", "discovery_team.py", "run_smoke.py", "compose.smoke.yaml", "uv.lock"):
        metadata["source_sha256"][filename] = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
    manifest = ROOT / (run_id + ".manifest.json")
    manifest.write_text(json.dumps(metadata, indent=2))
    print(f"Workspace: {workspace}", flush=True)
    print(f"Model: {MODEL}; reserve ${RESERVATION_USD:.2f}; key remaining ${before['limit_remaining']:.6f}", flush=True)
    cost_config = {MODEL: ModelCost(input=0.075, output=0.25, input_cache_write=0.075, input_cache_read=0.015)}
    logs = []
    try:
        preflight = eval(
            Task(name="glm_flash_preflight", dataset=[Sample(input="Reply with OK.", target="OK")],
                 solver=generate(), scorer=includes(),
                 config=GenerateConfig(max_tokens=1024, max_retries=0, timeout=60,
                                       reasoning_effort="low", cache=False,
                                       extra_body={"provider": {"max_price": {"prompt": 0.075, "completion": 0.25}}})),
            model=MODEL, log_dir=str(ROOT), log_realtime=True, log_buffer=1,
            model_cost_config=cost_config, display="plain",
        )
        logs.extend(preflight)
        if preflight[0].status != "success" or preflight[0].samples[0].error:
            raise RuntimeError(f"Model preflight failed; see {preflight[0].location}")
        if args.discovery:
            from discovery_team import roster_discovery
            selected_task = roster_discovery()
            print("Preflight passed; starting five agents with private names and no disclosed count.", flush=True)
        else:
            selected_task = collaboration_smoke()
            print("Preflight passed; starting three concurrent named agents.", flush=True)
        team = eval(
            selected_task, model=MODEL, log_dir=str(ROOT),
            log_realtime=True, log_buffer=1, log_shared=1,
            model_cost_config=cost_config, display="plain", sandbox_cleanup=True,
            metadata={"run_manifest": manifest.name},
        )
        logs.extend(team)
        metadata["status"] = team[0].status
        print(f"Team eval: {team[0].location}", flush=True)
    finally:
        metadata["logs"] = [log.location for log in logs]
        metadata["log_stats"] = [log.stats.model_dump(mode="json") for log in logs]
        metadata["key_usage_after"] = key_usage()
        metadata["account_delta_note"] = "Key usage changes can include other processes; use this run's logged model usage for attribution."
        if metadata["status"] == "running":
            metadata["status"] = "error"
        manifest.write_text(json.dumps(metadata, indent=2))
        print(f"Run manifest: {manifest}", flush=True)


if __name__ == "__main__":
    main()
