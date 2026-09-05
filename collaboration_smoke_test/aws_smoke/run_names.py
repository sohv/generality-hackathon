"""Local Inspect team histories, task-scoped Docker MCP files, remote names demo."""
import argparse
import asyncio
import fcntl
import hashlib
import importlib.metadata
import json
import os
from datetime import datetime, timezone

from dotenv import dotenv_values
from inspect_ai import Task, eval
from inspect_ai.agent import AgentSubmit, react, run
from inspect_ai.dataset import Sample
from inspect_ai.model import CompactionSummary, GenerateConfig, ModelCost, ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, scorer
from inspect_ai.solver import solver
from inspect_ai.tool import tool
from inspect_ai.util import time_limit, token_limit, turn_limit

from collaboration_prompt import with_collaboration
from run_smoke import api, key_usage
from smoke_team import MODEL
from .common import BASE, ROOT, cleanup, connection, create, docker, freeze, read_names

PRIVATE_NAMES = ("Mira", "Felix", "Zara", "Arun", "Lena", "Oscar", "Bea", "Theo", "Iris", "Hugo")

def prompt(name):
    return with_collaboration(
        f"Your name is {name}.\n\n"
        "Create /workspace/names.txt containing every participant's name, including your own, "
        "exactly once in alphabetical order. Put one name on each line with no other text. "
        "Submit when the file is complete.")

@tool
def submit_file(context, cid, name, submissions):
    async def execute(discovered_names: list[str], peer_count: int, answer: str) -> str:
        """Submit the completed names.txt file and your assessment.

        Args:
            discovered_names: Participant names you discovered, including yourself.
            peer_count: Number of participants other than yourself.
            answer: Brief explanation of the completed file.
        """
        text = await asyncio.to_thread(read_names, context, cid)
        submissions[name] = {"discovered_names": discovered_names, "peer_count": peer_count,
                             "answer": answer, "file_at_submit": text}
        return answer
    return execute

@solver
def team(context, directory, roster, holder, limits):
    async def solve(state, generate):
        cid = await asyncio.to_thread(create, context, directory)
        holder["cid"] = cid
        submissions, results = {}, {}
        state.metadata.update(container=cid, context=context, submissions=submissions, agents=results)
        async def participant(name):
            server = connection(context, cid, directory, name)
            agent = react(prompt=None, tools=[server],
                          submit=AgentSubmit(name="submit", tool=submit_file(context, cid, name, submissions),
                                             keep_in_messages=True),
                          compaction=CompactionSummary(threshold=.75))
            try:
                output, limit = await run(agent, prompt(name), name=name,
                                          limits=[token_limit(limits["tokens_per_agent"]),
                                                  turn_limit(limits["turns_per_agent"]),
                                                  time_limit(limits["seconds_per_agent"])])
                export = {"messages": [m.model_dump(mode="json") for m in output.messages],
                          "output": output.output.model_dump(mode="json"),
                          "submitted": name in submissions, "limit": str(limit) if limit else None}
                (directory / (name + ".json")).write_text(json.dumps(export, indent=2))
                results[name] = {k:v for k,v in export.items() if k != "messages"}
            except Exception as exc:
                results[name] = {"error": repr(exc), "submitted": name in submissions}
        await asyncio.gather(*(participant(n) for n in roster))
        content = await asyncio.to_thread(freeze, context, cid, directory)
        holder["frozen"] = True
        state.output = ModelOutput.from_content(MODEL, content)
        (directory / "team.json").write_text(json.dumps(state.metadata, indent=2))
        return state
    return solve

@scorer(metrics=[accuracy()])
def check_names(context, directory, roster, holder):
    async def score(state, target):
        if not holder.get("frozen") and holder.get("cid"):
            content = await asyncio.to_thread(freeze, context, holder["cid"], directory)
            holder["frozen"] = True
            state.output = ModelOutput.from_content(MODEL, content)
        text = state.output.completion
        submissions = state.metadata.get("submissions", {})
        checks = {"exact_alphabetical_file": text in ("\n".join(sorted(roster)), "\n".join(sorted(roster))+"\n"),
                  "all_submitted": set(submissions) == set(roster),
                  "all_reported_roster": all(sorted(submissions.get(n, {}).get("discovered_names", [])) == sorted(roster) for n in roster),
                  "all_reported_peer_count": all(submissions.get(n, {}).get("peer_count") == len(roster)-1 for n in roster)}
        report = {"passed": checks["exact_alphabetical_file"],
                  "scoring_rule": "final_names_file_only",
                  "checks": checks, "content": text,
                  "agents": state.metadata.get("agents", {}), "submissions": submissions}
        (directory / "result.json").write_text(json.dumps(report, indent=2))
        return Score(value=CORRECT if report["passed"] else INCORRECT, answer=text,
                     explanation=json.dumps(checks), metadata=report)
    return score

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", required=True)
    parser.add_argument("--agents", type=int, choices=range(1,11), default=10)
    parser.add_argument("--turns", type=int, choices=range(1,201), default=200)
    args = parser.parse_args()
    endpoint = json.loads(docker(args.context, "context", "inspect", args.context).stdout)[0]["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("ssh://"):
        raise RuntimeError("The AWS model demo requires an SSH Docker context; use validate_mcp for local transport checks")
    os.environ["OPENROUTER_API_KEY"] = dotenv_values(ROOT / ".env")["OPENROUTER_API_KEY"]
    lock = (ROOT / ".smoke-budget.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = key_usage()
    price = next(m for m in api("models")["data"] if m["id"] == "z-ai/glm-5.3-flash")
    if before["limit_remaining"] is None or before["limit_remaining"] < 2.50:
        raise RuntimeError("Cannot reserve $2.50")
    if float(price["pricing"]["prompt"]) > .075/1e6 or float(price["pricing"]["completion"]) > .25/1e6:
        raise RuntimeError("Endpoint prices exceed the declared ceiling")
    max_call_usd = price["context_length"] * .075/1e6 + 8192 * .25/1e6
    if 1.00 + args.agents * max_call_usd > 2.50:
        raise RuntimeError("Cost stop plus concurrent calls exceeds the $2.50 reservation")
    directory = BASE / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True)
    roster = PRIVATE_NAMES[:args.agents]
    limits = {"turns_per_agent": args.turns, "tokens_per_agent": 5_000_000,
              "seconds_per_agent": 1800, "team_seconds": 1860, "team_cost_stop_usd": 1.00}
    (directory / "prompts.json").write_text(json.dumps({n:prompt(n) for n in roster}, indent=2))
    manifest = {"model": MODEL, "private_roster": roster, "context": args.context, "endpoint": endpoint,
                "reserved_usd": 2.50, "key_usage_before": before, "pricing": price,
                "limits": limits, "max_inflight_cost_usd": args.agents * max_call_usd,
                "status": "running", "condition": "collaboration_note_count_hidden",
                "scoring_rule": "final_names_file_only",
                "transport": "local MCP stdio -> SSH Docker context -> one text-file-only container",
                "versions": {p:importlib.metadata.version(p) for p in ("inspect-ai", "openai", "mcp")}}
    source = directory / "source"
    source.mkdir()
    manifest["source_sha256"] = {}
    for path in [*BASE.glob("*.py"), ROOT / "collaboration_prompt.py", ROOT / "run_smoke.py",
                 ROOT / "smoke_team.py", ROOT / "pyproject.toml", ROOT / "uv.lock"]:
        relative = path.relative_to(ROOT)
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
        manifest["source_sha256"][str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    deployment = BASE / "local_state" / "deployment.json"
    if deployment.exists():
        manifest["aws_deployment"] = json.loads(deployment.read_text())
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    holder = {}
    task = Task(name="aws_names_team", version=3, dataset=[Sample(id="names-team", input="Names smoke test")],
                solver=team(args.context, directory, roster, holder, limits),
                scorer=check_names(args.context, directory, roster, holder),
                time_limit=limits["team_seconds"], cost_limit=limits["team_cost_stop_usd"],
                config=GenerateConfig(max_tokens=8192, max_connections=args.agents, max_retries=0,
                                      attempt_timeout=60, reasoning_effort="low", temperature=.5,
                                      extra_body={"provider":{"max_price":{"prompt":.075,"completion":.25}}}))
    print(f"AWS names demo output: {directory}", flush=True)
    print(f"Limits: {limits}; reserved $2.50; key remaining ${before['limit_remaining']:.6f}", flush=True)
    try:
        logs = eval(task, model=MODEL, log_dir=str(ROOT), log_realtime=True, log_buffer=1,
                    display="plain", model_cost_config={MODEL:ModelCost(input=.075,output=.25,input_cache_write=.075,input_cache_read=.015)},
                    metadata={"manifest":str(directory / "manifest.json")})
        manifest.update(status=logs[0].status, logs=[l.location for l in logs],
                        stats=[l.stats.model_dump(mode="json") for l in logs])
    finally:
        if holder.get("cid"):
            if not holder.get("frozen"):
                try:
                    freeze(args.context, holder["cid"], directory)
                except Exception as exc:
                    manifest["export_error"] = repr(exc)
            cleanup(args.context, holder["cid"])
        try:
            manifest["key_usage_after"] = key_usage()
        finally:
            (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(directory)

if __name__ == "__main__":
    main()
