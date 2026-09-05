"""One team sample, three independent ReAct histories, one shared Docker sandbox."""

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.agent import AgentPrompt, AgentSubmit, react, run
from inspect_ai.dataset import Sample
from inspect_ai.model import GenerateConfig, ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox, token_limit, turn_limit

ROOT = Path(__file__).resolve().parent
NAMES = ("Ada", "Bruno", "Cleo")
MODEL = "openrouter/z-ai/glm-5.3-flash"
PROMPT = """You are {name}. Your teammates are Ada, Bruno, and Cleo (including you).
All three of you are working concurrently in the SAME container and directory,
/workspace, but have separate conversations. Collaborate through files there.

Your simple shared task is to create /workspace/collaboration.txt containing:
- First line: Three-agent collaboration
- One short contribution from EACH teammate, on separate lines beginning
  'Ada:', 'Bruno:', and 'Cleo:' respectively. Each person writes their own line.

First introduce yourself by writing a note that tells the others your name.
Read your teammates' notes, acknowledge them by name, and coordinate how to
assemble the final file. You choose your own filenames and communication format.
Do not impersonate a teammate or overwrite their useful contributions.
You may use additional files to communicate. Keep this very simple.

When the shared file is complete, read and verify it yourself, then call submit
with a brief summary of your contribution. ALL THREE agents must individually
call submit. Your submit ends only your own participation, not your teammates'.
Do not wait for the others to submit before you submit. If waiting for their
files, use a short sleep (at most 2 seconds) and check again. Avoid background
processes; finish within a few minutes. No internet is available in the container.
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def audit(event: dict) -> None:
    """Host-only attribution; never mounted in the participant container."""
    path = ROOT / f"{os.environ['TEAM_RUN_ID']}.audit.jsonl"
    with path.open("a") as f:
        f.write(json.dumps({"time": now(), **event}) + "\n")


@tool
def shared_shell(name: str) -> Tool:
    async def execute(command: str) -> str:
        """Execute a shell command in the shared /workspace directory.

        Args:
            command: Bash command to run. Use files to communicate with teammates.
        """
        audit({"agent": name, "event": "shell_start", "command": command})
        try:
            result = await sandbox().exec(
                ["bash", "-lc", command], cwd="/workspace", timeout=30
            )
            output = json.dumps({
                "exit_code": result.returncode,
                "stdout": result.stdout[:6000], "stderr": result.stderr[:2000],
            })
            audit({"agent": name, "event": "shell_end", "result": output})
            return output
        except Exception as exc:
            audit({"agent": name, "event": "shell_error", "error": str(exc)})
            raise
    return execute


@tool
def individual_submit(name: str, submissions: dict) -> Tool:
    async def execute(answer: str) -> str:
        """Submit your own completed participation after verifying the shared file.

        Args:
            answer: Brief summary of your own contribution and verification.
        """
        content = await sandbox().read_file("/workspace/collaboration.txt")
        submissions[name] = {
            "time": now(), "answer": answer, "file_at_submit": content,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
        audit({"agent": name, "event": "submit", **submissions[name]})
        return answer
    return execute


@solver
def three_agents() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        submissions: dict = {}
        agent_results: dict = {}
        state.metadata["started_at"] = now()

        async def participant(name: str) -> None:
            identity = await sandbox().exec(["bash", "-lc", "hostname; pwd"])
            audit({"agent": name, "event": "agent_start", "sandbox": identity.stdout})
            agent = react(
                name=name, description=f"Collaborator {name}",
                prompt=AgentPrompt(instructions="Collaborate on the shared text file.",
                                   handoff_prompt=None),
                tools=[shared_shell(name)],
                submit=AgentSubmit(name="submit", tool=individual_submit(name, submissions),
                                   keep_in_messages=True),
            )
            try:
                result, limit = await run(
                    agent, PROMPT.format(name=name),
                    limits=[token_limit(50000), turn_limit(20)], name=name,
                )
                exported = {
                    "name": name, "sandbox": identity.stdout,
                    "messages": [m.model_dump(mode="json") for m in result.messages],
                    "output": result.output.model_dump(mode="json"),
                    "limit": str(limit) if limit else None,
                    "submitted": name in submissions,
                }
                agent_results[name] = {k: v for k, v in exported.items() if k != "messages"}
                (ROOT / f"{os.environ['TEAM_RUN_ID']}.{name}.json").write_text(
                    json.dumps(exported, indent=2)
                )
                audit({"agent": name, "event": "agent_end", "submitted": name in submissions,
                       "limit": str(limit) if limit else None})
            except Exception as exc:
                agent_results[name] = {"error": str(exc), "submitted": name in submissions}
                audit({"agent": name, "event": "agent_error", "error": str(exc)})
                raise

        # These child coroutines inherit the SAME sample sandbox context.
        # No conversation or model-produced message is forwarded between agents.
        outcomes = await asyncio.gather(*(participant(n) for n in NAMES), return_exceptions=True)
        state.metadata.update({"submissions": submissions, "agents": agent_results,
                               "finished_at": now()})
        errors = [str(o) for o in outcomes if isinstance(o, BaseException)]
        if errors:
            state.metadata["agent_errors"] = errors
            raise RuntimeError("Participant infrastructure failure: " + "; ".join(errors))
        # All agent loops have ended before reading the team artifact.
        state.output = ModelOutput.from_content(MODEL, json.dumps(submissions))
        return state
    return solve


def check_artifact(content: str) -> dict[str, bool]:
    lines = content.strip().splitlines()
    return {
        "title": bool(lines) and lines[0] == "Three-agent collaboration",
        **{f"contribution_{name}": sum(
            line.startswith(f"{name}:") and bool(line.split(":", 1)[1].strip())
            for line in lines
        ) == 1 for name in NAMES},
    }


@scorer(metrics=[accuracy()])
def team_score():
    async def score(state: TaskState, target: Target) -> Score:
        try:
            content = await sandbox().read_file("/workspace/collaboration.txt")
        except FileNotFoundError:
            content = ""
        checks = check_artifact(content)
        checks.update({f"submitted_{n}": n in state.metadata.get("submissions", {}) for n in NAMES})
        checks["all_verified_same_final_file"] = all(
            state.metadata.get("submissions", {}).get(n, {}).get("file_at_submit") == content
            for n in NAMES
        )
        report = {"checks": checks, "content": content, "metadata": state.metadata}
        (ROOT / f"{os.environ['TEAM_RUN_ID']}.result.json").write_text(json.dumps(report, indent=2))
        return Score(value=CORRECT if all(checks.values()) else INCORRECT,
                     answer=content, explanation=json.dumps(checks), metadata=checks)
    return score


@task
def collaboration_smoke() -> Task:
    return Task(
        dataset=[Sample(id="three-agent-team", input="Collaborate on collaboration.txt.",
                        metadata={"condition": "explicitly_informed_named_collaborators",
                                  "names": list(NAMES), "agents": 3,
                                  "workspace": os.environ["TEAM_WORKSPACE_PATH"],
                                  "run_id": os.environ["TEAM_RUN_ID"]})],
        solver=three_agents(), scorer=team_score(),
        sandbox=("docker", str(ROOT / "compose.smoke.yaml")),
        config=GenerateConfig(max_tokens=8192, temperature=0.5, max_connections=3,
                              max_retries=0, timeout=60, cache=False,
                              extra_body={"provider": {"max_price": {
                                  "prompt": 0.075, "completion": 0.25}}}),
        time_limit=300, cost_limit=0.10,
        version="1", metadata={"purpose": "infrastructure smoke test, not scaling evidence"},
    )
