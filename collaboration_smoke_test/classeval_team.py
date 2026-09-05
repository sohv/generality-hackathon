"""ClassEval prompt-preserving shared-workspace pilot (not standard pass@k)."""
import asyncio
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.agent import AgentSubmit, react, run
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, CompactionSummary, GenerateConfig, ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, accuracy, scorer
from inspect_ai.solver import solver
from inspect_ai.tool import tool
from inspect_ai.util import sandbox, time_limit, token_limit, turn_limit

from smoke_team import MODEL, ROOT, now
from collaboration_prompt import with_collaboration

BASE = ROOT / "classeval"
IMAGE = "ghcr.io/generality-labs/inspect-eval-class_eval:2026-07-28@sha256:d40b26396195eb457a34aa1c4f50b58c44a489351a58a240eb09d82e39b48915"
DOCKER = shutil.which("docker") or "/usr/local/bin/docker"
RECORD = json.loads((BASE / "data/ClassEval_39.json").read_text())
_spec = importlib.util.spec_from_file_location("classeval_upstream_utils", BASE / "upstream/utils.py")
_utils = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_utils)
ORIGINAL_PROMPT = _utils.construct_prompt(RECORD)
PROMPT = (ORIGINAL_PROMPT if os.environ.get("CLASSEVAL_CONDITION") == "unaware"
          else with_collaboration(ORIGINAL_PROMPT))
_tree = ast.parse((BASE / "upstream/class_eval.py").read_text())
def upstream_constant(name):
    return next(ast.literal_eval(n.value) for n in ast.walk(_tree)
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
SYSTEM = upstream_constant("INSTRUCTION")
TEST_RUNNER = upstream_constant("TEST_RUNNER")

def outdir():
    return Path(os.environ["CLASSEVAL_RUN_DIR"])

def audit(**event):
    with (outdir() / "audit.jsonl").open("a") as f:
        f.write(json.dumps({"time": now(), **event}) + "\n")

async def snapshot():
    try:
        return await sandbox().read_file("/workspace/solution.py")
    except FileNotFoundError:
        return ""

@tool
def shell(label):
    async def execute(command: str) -> str:
        """Execute Bash in /workspace. The class skeleton is in solution.py.

        Args:
            command: Command to inspect, edit, or test the implementation.
        """
        before = await snapshot()
        audit(agent=label, event="shell_start", command=command, solution_before=before)
        result = await sandbox().exec(["bash", "-lc", command], cwd="/workspace", timeout=30)
        output = json.dumps({"exit_code": result.returncode, "stdout": result.stdout[:10000], "stderr": result.stderr[:4000]})
        audit(agent=label, event="shell_end", result=output, solution_after=await snapshot())
        return output
    return execute

@tool
def finish(label, submissions):
    async def execute(answer: str) -> str:
        """Submit the completed implementation in /workspace/solution.py for evaluation.

        Write the complete Python code to that file before calling this tool.

        Args:
            answer: Brief description of the completed implementation.
        """
        code = await snapshot()
        submissions[label] = {"time": now(), "answer": answer, "code": code,
                              "sha256": hashlib.sha256(code.encode()).hexdigest()}
        audit(agent=label, event="submit", **submissions[label])
        return answer
    return execute

async def continue_only_tools(state):
    # Do not inject continuation instructions into the verbatim benchmark dialogue.
    return bool(state.output.message.tool_calls)

async def freeze(state):
    cid = state.metadata["container"]
    await asyncio.to_thread(subprocess.run, [DOCKER, "pause", cid], check=True, capture_output=True)
    try:
        p = Path(os.environ["TEAM_WORKSPACE_PATH"]) / "solution.py"
        code = p.read_text() if p.is_file() and not p.is_symlink() else ""
        (outdir() / "final_solution.py").write_text(code)
    finally:
        await asyncio.to_thread(subprocess.run, [DOCKER, "kill", cid], check=True, capture_output=True)
    state.metadata["frozen_at"] = now()
    state.output = ModelOutput.from_content(MODEL, code)
    (outdir() / "team.json").write_text(json.dumps(state.metadata, indent=2))

@solver
def participants():
    async def solve(state, generate):
        submissions, agents = {}, {}
        state.metadata.update(submissions=submissions, agents=agents)
        identity = await sandbox().exec(["bash", "-lc", "hostname; pwd"])
        cid = identity.stdout.splitlines()[0]
        state.metadata["container"] = cid
        audit(event="team_start", container=cid, sandbox=identity.stdout)

        async def participant(label):
            audit(event="agent_start", agent=label, container=cid)
            agent = react(prompt=None, tools=[shell(label)],
                          submit=AgentSubmit(name="submit", tool=finish(label, submissions), keep_in_messages=True),
                          compaction=CompactionSummary(threshold=0.75),
                          on_continue=continue_only_tools)
            try:
                result, limit = await run(agent, [ChatMessageSystem(content=SYSTEM), ChatMessageUser(content=PROMPT)],
                                          limits=[token_limit(150000), turn_limit(12), time_limit(300)], name=label)
                exported = {"messages": [m.model_dump(mode="json") for m in result.messages],
                            "output": result.output.model_dump(mode="json"), "limit": str(limit) if limit else None,
                            "submitted": label in submissions}
                (outdir() / f"{label}.json").write_text(json.dumps(exported, indent=2))
                agents[label] = {k: v for k, v in exported.items() if k != "messages"}
            except Exception as exc:
                agents[label] = {"error": repr(exc), "submitted": label in submissions}
                audit(event="agent_error", agent=label, error=repr(exc))
            except asyncio.CancelledError:
                agents[label] = {"error": "cancelled by enclosing run", "submitted": label in submissions}
                raise
            finally:
                audit(event="agent_end", agent=label)

        await asyncio.gather(*(participant(f"agent_{i}") for i in range(1, 4)))
        await freeze(state)
        return state
    return solve

def evaluate_code(code):
    """Original unittest payload, in a fresh container with no participant mounts."""
    name = "classeval-score-" + uuid.uuid4().hex[:12]
    payload = "\n".join([code, RECORD["test"], TEST_RUNNER])
    try:
        result = subprocess.run([DOCKER, "run", "--rm", "-i", "--name", name,
                                 "--network", "none", "--cpus", "1", "--memory", "512m",
                                 IMAGE, "python", "-"], input=payload, text=True,
                                capture_output=True, timeout=30)
        count = re.search(r"Ran (\d+) tests?", result.stderr)
        return {"outcome": "pass" if result.returncode == 0 else "fail", "returncode": result.returncode,
                "tests_run": int(count.group(1)) if count else 0,
                "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout", "tests_run": None}
    finally:
        subprocess.run([DOCKER, "rm", "-f", name], capture_output=True)

@scorer(metrics=[accuracy()])
def final_artifact():
    async def score(state, target):
        if not state.metadata.get("frozen_at"):
            # Inspect also scores after a common time/token limit interrupts the solver.
            await freeze(state)
        report = await asyncio.to_thread(evaluate_code, state.output.completion)
        report["all_submitted"] = len(state.metadata.get("submissions", {})) == 3
        report["agent_errors"] = {k: v["error"] for k, v in state.metadata.get("agents", {}).items() if "error" in v}
        report["agent_limits"] = {k: v["limit"] for k, v in state.metadata.get("agents", {}).items() if v.get("limit")}
        (outdir() / "result.json").write_text(json.dumps(report, indent=2))
        return Score(value=CORRECT if report["outcome"] == "pass" else INCORRECT,
                     answer=state.output.completion, explanation=json.dumps(report), metadata=report)
    return score

@task
def classeval_shared():
    return Task(dataset=[Sample(id=RECORD["task_id"], input=PROMPT)],
                solver=participants(), scorer=final_artifact(),
                sandbox=("docker", str(BASE / "compose.yaml")),
                config=GenerateConfig(max_tokens=32768, temperature=0.5, max_connections=3,
                                      max_retries=0, timeout=120, attempt_timeout=90, reasoning_effort="low", cache=False,
                                      extra_body={"provider": {"max_price": {"prompt": 0.075, "completion": 0.25}}}),
                time_limit=600, cost_limit=0.10, version="3",
                metadata={"condition": "unaware_shared_workspace" if PROMPT == ORIGINAL_PROMPT else "collaboration_note_count_hidden",
                          "agents": 3,
                          "protocol": "Original task plus optional collaboration note; neutral tools; final frozen artifact scored."})
