"""Ten local, shared-workspace team attempts at powers of two from 2 to 1024."""
import argparse
import asyncio
import csv
import fcntl
import hashlib
import importlib.metadata
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from inspect_ai import Task, eval
from inspect_ai.agent import AgentSubmit, agent, react, run
from inspect_ai.dataset import Sample
from inspect_ai.log import read_eval_log
from inspect_ai.model import CompactionSummary, GenerateConfig, ModelCost, ModelOutput
from inspect_ai.scorer import Score, mean, scorer
from inspect_ai.solver import solver
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import time_limit, token_limit, turn_limit

from aws_smoke.common import IMAGE, ROOT, context_name, docker
from aws_smoke.run_names import prompt
from run_smoke import api, key_usage
from smoke_team import MODEL
from .scoring import name_coverage

BASE = ROOT / "local_sweep"
CONTEXT = context_name()
SIZES = [2**i for i in range(1, 11)]
LIMITS = {"turns_per_agent": 200, "tokens_per_agent": 5_000_000,
          "seconds_per_agent": 1800, "team_seconds": 1860}


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, obj):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(obj, indent=2))
    temp.replace(path)


def roster_for_sweep():
    # Equal-length pronounceable private pseudonyms; no count/index in a name.
    rng = random.Random(20260905)
    roster = []
    while len(roster) < 1024:
        name = "".join(rng.choice("bcdfghjklmnprstvwz") + rng.choice("aeiou") for _ in range(4)).capitalize()
        if name not in roster:
            roster.append(name)
    return roster


class Workspace:
    """File-only host tools, one clean bind mount, and private attribution."""
    def __init__(self, directory):
        self.directory = directory
        self.path = directory / "live_workspace"
        self.path.mkdir()
        self.active = True
        self.cid = None
        self.audit = (directory / "audit.jsonl").open("a", buffering=1)

    def create(self):
        self.cid = docker(CONTEXT, "run", "-d", "--network", "none", "--init",
                          "--cpus", "1", "--memory", "512m", "--pids-limit", "128",
                          "--label", "generality.purpose=local-names-sweep", "--workdir", "/workspace",
                          "--mount", f"type=bind,source={self.path},target=/workspace",
                          IMAGE, "tail", "-f", "/dev/null").stdout.strip()
        (self.directory / "container.json").write_text(docker(CONTEXT, "inspect", self.cid).stdout)

    def operation(self, owner, payload):
        if not self.active:
            raise RuntimeError("The shared workspace is frozen")
        start = time.monotonic()
        try:
            if payload["op"] == "list":
                result = sorted(p.name for p in self.path.glob("*.txt") if p.is_file() and not p.is_symlink())
            else:
                name = payload["name"]
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.txt", name):
                    raise ValueError("Use a flat filename ending in .txt")
                path = self.path / name
                if path.is_symlink():
                    raise ValueError("Symlinks are not supported")
                if payload["op"] == "read":
                    result = {"text": path.read_text()}
                else:
                    content = payload["text"]
                    if len(content.encode()) > 16384:
                        raise ValueError("Text must be at most 16384 bytes")
                    fd, temporary = tempfile.mkstemp(dir=self.path)
                    try:
                        with os.fdopen(fd, "w") as f:
                            f.write(content)
                        os.replace(temporary, path)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                    result = {"written": name}
            self.audit.write(json.dumps({"time": now(), "agent": owner, "operation": payload,
                                         "result": result, "duration_seconds": time.monotonic()-start}) + "\n")
            return json.dumps(result)
        except Exception as exc:
            self.audit.write(json.dumps({"time": now(), "agent": owner, "operation": payload,
                                         "error": repr(exc)}) + "\n")
            if isinstance(exc, FileNotFoundError):
                raise ToolError(f"File '{payload.get('name', '')}' was not found in /workspace.") from None
            if isinstance(exc, ValueError):
                raise ToolError(str(exc)) from None
            # Host paths include private run metadata; never return them to a model.
            raise ToolError(f"The file operation failed ({type(exc).__name__}).") from None

    def read_names(self):
        path = self.path / "names.txt"
        return path.read_text() if path.exists() else ""

    def freeze(self):
        if not self.active:
            path = self.directory / "workspace" / "names.txt"
            return path.read_text() if path.exists() else ""
        # All model writers have finished/cancelled. Refuse any subsequent tool write.
        self.active = False
        if self.cid:
            docker(CONTEXT, "pause", self.cid)
        try:
            shutil.copytree(self.path, self.directory / "workspace")
            content = self.read_names()
        finally:
            if self.cid:
                docker(CONTEXT, "kill", self.cid, check=False)
            self.audit.close()
        return content

    def cleanup(self):
        if self.cid:
            docker(CONTEXT, "rm", "-f", self.cid, check=False)


@tool
def list_files(workspace, owner):
    async def execute() -> str:
        """List the text files in /workspace."""
        return workspace.operation(owner, {"op": "list"})
    return execute


@tool
def read_file(workspace, owner):
    async def execute(name: str) -> str:
        """Read a .txt file in /workspace.

        Args:
            name: Filename, such as notes.txt.
        """
        return workspace.operation(owner, {"op": "read", "name": name})
    return execute


@tool
def write_file(workspace, owner):
    async def execute(name: str, text: str) -> str:
        """Create or replace a .txt file in /workspace with UTF-8 text.

        Args:
            name: Filename, such as notes.txt.
            text: Complete file contents, at most 16384 bytes.
        """
        return workspace.operation(owner, {"op": "write", "name": name, "text": text})
    return execute


@tool
def submit(workspace, owner, submissions):
    async def execute(discovered_names: list[str], peer_count: int, answer: str) -> str:
        """Submit the completed names.txt file and your assessment.

        Args:
            discovered_names: Participant names you discovered, including yourself.
            peer_count: Number of participants other than yourself.
            answer: Brief explanation of the completed file.
        """
        submissions[owner] = {"discovered_names": discovered_names, "peer_count": peer_count,
                              "answer": answer, "file_at_submit": workspace.read_names(), "time": now()}
        return answer
    return execute


@agent
def capture_state(inner, holder):
    async def execute(state):
        holder["state"] = state
        return await inner(state)
    return execute


@solver
def team(workspace, directory, roster):
    async def solve(state, generate):
        await asyncio.to_thread(workspace.create)
        results, submissions = {}, {}
        state.metadata.update(agents=results, submissions=submissions, container=workspace.cid)
        ready = 0
        start = asyncio.Event()
        all_ready = asyncio.Event()
        async def participant(name):
            nonlocal ready
            holder = {}
            inner = react(prompt=None,
                          tools=[list_files(workspace, name), read_file(workspace, name), write_file(workspace, name)],
                          submit=AgentSubmit(name="submit", tool=submit(workspace, name, submissions), keep_in_messages=True),
                          compaction=CompactionSummary(threshold=.75))
            ready += 1
            if ready == len(roster):
                all_ready.set()
            await start.wait()
            row = {"started_at": now(), "submitted": False, "limit": None, "error": None}
            try:
                output, limit = await run(capture_state(inner, holder), prompt(name), name=name,
                                          limits=[turn_limit(LIMITS["turns_per_agent"]),
                                                  token_limit(LIMITS["tokens_per_agent"]),
                                                  time_limit(LIMITS["seconds_per_agent"])])
                holder["state"] = output
                row["limit"] = str(limit) if limit else None
            except asyncio.CancelledError:
                row["error"] = "cancelled_by_team_limit_or_interrupt"
                raise
            except Exception as exc:
                row["error"] = repr(exc)
            finally:
                row.update(submitted=name in submissions, completed_at=now())
                results[name] = row
                export = dict(row)
                if holder.get("state") is not None:
                    export["messages"] = [m.model_dump(mode="json") for m in holder["state"].messages]
                    export["output"] = holder["state"].output.model_dump(mode="json")
                save(directory / "agents" / (name + ".json"), export)
                save(directory / "progress.json", {"expected": len(roster), "finished": len(results),
                                                     "submitted": len(submissions), "updated_at": now()})
        tasks = [asyncio.create_task(participant(name)) for name in roster]
        try:
            await all_ready.wait()
            state.metadata["release_barrier_at"] = now()
            start.set()
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        content = await asyncio.to_thread(workspace.freeze)
        state.output = ModelOutput.from_content(MODEL, content)
        save(directory / "team.json", state.metadata)
        return state
    return solve


@scorer(metrics=[mean()])
def coverage(workspace, directory, roster):
    async def score(state, target):
        text = await asyncio.to_thread(workspace.freeze)
        state.output = ModelOutput.from_content(MODEL, text)
        report = name_coverage(text, roster)
        report.update(scoring_rule="unique_expected_names_present_percent", content=text,
                      agents=state.metadata.get("agents", {}), submissions=state.metadata.get("submissions", {}))
        save(directory / "result.json", report)
        return Score(value=report["coverage_percent"], answer=text,
                     explanation=f"{report['correct_count']}/{len(roster)} expected names present",
                     metadata=report)
    return score


def verification(log, directory, roster):
    sample = log.samples[0]
    spans = {e.id:e.name for e in sample.events if e.event == "span_begin" and e.type == "agent"}
    models = [e for e in sample.events if e.event == "model"]
    checks = {"expected_agent_count": sorted(spans.values()) == sorted(roster)}
    owners = {}
    for event in models:
        if event.output:
            for choice in event.output.choices:
                for call in choice.message.tool_calls or []:
                    owners[call.id] = spans.get(event.span_id)
    for sid, name in spans.items():
        calls = [e for e in models if e.span_id == sid]
        first = calls[0].input if calls else []
        checks[name + "_initial_prompt"] = len(first) == 1 and first[0].text == prompt(name)
        checks[name + "_private_identity"] = bool(first) and not any(n in first[0].text for n in roster if n != name)
        checks[name + "_independent_history"] = all(owners.get(m.tool_call_id) == name for e in calls for m in e.input if m.role == "tool")
    c = json.loads((directory / "container.json").read_text())[0]
    checks["network_none"] = c["HostConfig"]["NetworkMode"] == "none"
    checks["only_workspace_mounted"] = len(c["Mounts"]) == 1 and c["Mounts"][0]["Destination"] == "/workspace" and c["Mounts"][0]["Source"] == str(directory / "live_workspace")
    text = (directory / "workspace" / "names.txt").read_text() if (directory / "workspace" / "names.txt").exists() else ""
    checks["scored_exported_file"] = sample.output.completion == text
    checks["recomputed_percentage"] = sample.scores["coverage"].value == name_coverage(text, roster)["coverage_percent"]
    intervals = []
    for e in models:
        if e.completed:
            intervals.extend([(e.timestamp, 1), (e.completed, -1)])
    active = peak = 0
    for _, delta in sorted(intervals):
        active += delta
        peak = max(peak, active)
    report = {"checks": checks, "passed": all(checks.values()), "model_calls": len(models),
              "peak_completed_call_concurrency": peak,
              "model_errors": sum(bool(e.error) for e in models),
              "unaccounted_model_calls": sum(not e.output or not e.output.usage for e in models),
              "compactions": sum(e.event == "compaction" for e in sample.events),
              "model_calls_per_agent": {n:sum(e.span_id == sid for e in models) for sid,n in spans.items()}}
    save(directory / "verification.json", report)
    return report


def write_summary(batch, rows):
    save(batch / "summary.json", rows)
    if rows:
        with (batch / "summary.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    table = "| Agents | Names | Coverage | Seconds | Model cost | API peak | Errors |\n|---:|---:|---:|---:|---:|---:|---:|\n"
    for row in rows:
        table += f"| {row['agents']} | {row['correct_count']} | {row['coverage_percent']:.2f}% | {row['seconds']:.1f} | ${row['logged_cost_usd']:.5f} | {row['api_peak']} | {row['agent_errors']} |\n"
    (batch / "REPORT.md").write_text("# Local names sweep\n\nOne team attempt per size; exploratory data, with no error bars or fitted scaling law.\n\n" + table + "\nPrimary score is unique expected names present / team size. Ordering, duplicate lines, and unexpected names are separate diagnostics.\n\nAll team histories are launched together; at most 128 API calls run concurrently. Larger teams queue requests. Local file tools access one clean workspace mounted into one network-disabled Docker container per team.\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=25)
    parser.add_argument("--connections", type=int, default=128)
    parser.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    parser.add_argument("--coordinator", type=Path, help="Parent-owned parallel allocation manifest")
    parser.add_argument("--output", type=Path, help="Explicit parent-owned batch directory")
    args = parser.parse_args()
    if any(n not in SIZES for n in args.sizes) or args.connections < 1:
        raise ValueError("Use powers of two from 2 to 1024 and positive concurrency")
    os.environ["OPENROUTER_API_KEY"] = dotenv_values(ROOT / ".env")["OPENROUTER_API_KEY"]
    if args.coordinator:
        coordinator = json.loads(args.coordinator.read_text())
        allocation = coordinator["allocations"][str(args.sizes[0])]
        if len(args.sizes) != 1 or args.budget != allocation["budget"] or args.connections != allocation["connections"] or str(args.output) != allocation["output"]:
            raise ValueError("Child run differs from its parallel coordinator allocation")
        os.kill(coordinator["pid"], 0)
    else:
        lock = (ROOT / ".smoke-budget.lock").open("w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    before = key_usage()
    if before["limit_remaining"] is None or before["limit_remaining"] < args.budget:
        raise RuntimeError("Insufficient key allowance to reserve the batch budget")
    price = next(m for m in api("models")["data"] if m["id"] == "z-ai/glm-5.3-flash")
    if float(price["pricing"]["prompt"]) > .075/1e6 or float(price["pricing"]["completion"]) > .25/1e6:
        raise RuntimeError("Model price ceiling changed")
    max_call = price["context_length"]*.075/1e6 + 8192*.25/1e6
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch = args.output or BASE / "runs" / stamp
    batch.mkdir(parents=True)
    roster = roster_for_sweep()
    manifest = {"created_at": now(), "status": "running", "sizes": args.sizes,
                "budget_usd": args.budget, "max_api_connections": args.connections,
                "private_roster": roster, "name_seed": 20260905, "limits": LIMITS,
                "key_usage_before": before, "pricing": price, "max_call_reservation_usd": max_call,
                "transport": "local bounded text-file tools; one clean bind mount and Docker container per team",
                "source_sha256": {}, "versions": {p:importlib.metadata.version(p) for p in ("inspect-ai","openai","mcp")}}
    if args.coordinator:
        manifest["coordinator"] = str(args.coordinator)
    for path in [*BASE.glob("*.py"), ROOT/"collaboration_prompt.py", ROOT/"aws_smoke/run_names.py", ROOT/"aws_smoke/common.py", ROOT/"uv.lock"]:
        rel = path.relative_to(ROOT)
        dest = batch/"source"/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())
        manifest["source_sha256"][str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    save(batch/"manifest.json", manifest)
    rows = []
    spent = unknown_reserved = 0.0
    print(f"LOCAL SWEEP: {batch}", flush=True)
    try:
        for n in args.sizes:
            connections = min(n, args.connections)
            headroom = connections * max_call
            stop = args.budget - spent - unknown_reserved - headroom
            if stop <= 0:
                manifest.update(status="budget_stopped", remaining_sizes=[k for k in args.sizes if k not in [r['agents'] for r in rows]])
                break
            current = key_usage()
            if current["limit_remaining"] is None or current["limit_remaining"] < stop + headroom:
                manifest.update(status="allowance_stopped")
                break
            directory = batch/f"n{n:04d}"
            directory.mkdir()
            (directory/"agents").mkdir()
            names = roster[:n]
            save(directory/"prompts.json", {name:prompt(name) for name in names})
            run_meta = {"agents": n, "connections": connections, "cost_stop_usd": stop,
                        "inflight_headroom_usd": headroom, "limits": LIMITS,
                        "scoring_rule": "unique_expected_names_present_percent", "status": "running"}
            save(directory/"manifest.json", run_meta)
            manifest["active_team"] = n
            save(batch/"manifest.json", manifest)
            workspace = Workspace(directory)
            started = time.monotonic()
            print(f"Starting N={n}; API concurrency cap={connections}; team cost stop=${stop:.4f}", flush=True)
            try:
                task = Task(name=f"local_names_n{n:04d}", version=1,
                            dataset=[Sample(id=f"team-{n}", input="Names team attempt")],
                            solver=team(workspace, directory, names), scorer=coverage(workspace,directory,names),
                            time_limit=LIMITS["team_seconds"], cost_limit=stop,
                            config=GenerateConfig(max_tokens=8192,max_connections=connections,adaptive_connections=False,
                                                  max_retries=0,attempt_timeout=60,reasoning_effort="low",temperature=.5,
                                                  extra_body={"provider":{"max_price":{"prompt":.075,"completion":.25}}}))
                logs = eval(task, model=MODEL, log_dir=str(ROOT), log_realtime=True, log_buffer=1, display="plain",
                            model_cost_config={MODEL:ModelCost(input=.075,output=.25,input_cache_write=.075,input_cache_read=.015)},
                            metadata={"batch_directory":str(batch),"run_directory":str(directory),"agent_count":n})
                if not logs:
                    run_meta.update(status="interrupted",error="Inspect returned no completed evaluation log")
                    manifest.update(status="interrupted",remaining_sizes=[k for k in args.sizes if k >= n])
                    break
                run_meta.update(status=logs[0].status, logs=[l.location for l in logs],
                                stats=logs[0].stats.model_dump(mode="json"))
            except BaseException as exc:
                run_meta.update(status="error",error=repr(exc))
                raise
            finally:
                try:
                    if workspace.active:
                        workspace.freeze()
                finally:
                    workspace.cleanup()
                    save(directory/"manifest.json", run_meta)
            elapsed = time.monotonic()-started
            log = read_eval_log(logs[0].location, resolve_attachments=True)
            if not log.samples or not (directory / "result.json").exists():
                spent += sum(u.total_cost or 0 for u in log.stats.model_usage.values())
                unknown_reserved += headroom
                manifest.update(status="incomplete_team",remaining_sizes=[k for k in args.sizes if k >= n])
                break
            v = verification(log, directory, names)
            result = json.loads((directory/"result.json").read_text())
            cost = sum(u.total_cost or 0 for u in log.stats.model_usage.values())
            spent += cost
            unknown_reserved += v["unaccounted_model_calls"] * max_call
            rows.append({"agents":n,"correct_count":result["correct_count"],"coverage_percent":result["coverage_percent"],
                         "seconds":elapsed,"logged_cost_usd":cost,"api_peak":v["peak_completed_call_concurrency"],
                         "agent_errors":sum(bool(r.get('error')) for r in result['agents'].values()),
                         "submitted":len(result["submissions"]),"model_calls":v["model_calls"],
                         "unexpected_names":len(result["unexpected_names"]),"duplicate_lines":result["duplicate_lines"],
                         "verification_passed":v["passed"],"eval":logs[0].location})
            manifest.update(logged_spend_usd=spent,unknown_usage_reservation_usd=unknown_reserved)
            write_summary(batch,rows)
            save(batch/"manifest.json",manifest)
            print(f"N={n}: {result['correct_count']}/{n} = {result['coverage_percent']:.2f}%; ${cost:.6f}; {elapsed:.1f}s",flush=True)
            del log, logs
            if not v["passed"]:
                manifest["status"]="verification_failed"
                break
        else:
            manifest["status"]="complete"
    except BaseException as exc:
        manifest.update(status="error",error=repr(exc))
        raise
    finally:
        manifest.update(completed_at=now(),logged_spend_usd=spent,unknown_usage_reservation_usd=unknown_reserved)
        try:
            manifest["key_usage_after"]=key_usage()
        finally:
            save(batch/"manifest.json",manifest)
            write_summary(batch,rows)
    print(f"SWEEP STATUS: {manifest['status']}; known model spend=${spent:.6f}; {batch}",flush=True)


if __name__ == "__main__":
    main()
