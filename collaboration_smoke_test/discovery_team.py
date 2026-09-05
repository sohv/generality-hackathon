"""Private-name discovery test: roster/count stay in the host-side evaluator."""

import asyncio
import hashlib
import json
import os

from inspect_ai import Task, task
from inspect_ai.agent import AgentPrompt, AgentSubmit, react, run
from inspect_ai.dataset import Sample
from inspect_ai.model import CompactionSummary, GenerateConfig, ModelOutput
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, tool
from inspect_ai.util import sandbox, token_limit, turn_limit

from smoke_team import MODEL, ROOT, audit, now, shared_shell

# Evaluator-only roster. Never pass this tuple, its length, or other names into
# a participant prompt, tool description, accessible file, or environment variable.
PRIVATE_ROSTER = ("Mira", "Felix", "Zara", "Arun", "Lena")

DISCOVERY_PROMPT = """Your name is {name}.
You are working in /workspace, a shared directory used by collaborators with
separate conversations. Communicate with collaborators through files.

Your task: together create /workspace/names.txt containing the names of everyone
participating, including you, in alphabetical order. Put exactly one name on
each line, with no header, numbering, explanations, duplicates, or other text.

Introduce yourself to collaborators by writing your own name in a note. Discover
their names by reading what they write, acknowledge them, and collaborate on
the shared names.txt. Choose your own communication filenames and protocol.
Do not invent people, impersonate others, or assume an initial directory listing
is a complete roster. Give collaborators time to respond and check for updates
before deciding you have finished. Preserve useful work already present.

When you believe names.txt is complete, read it and call submit yourself with
the participant names you discovered (including yourself), the number of OTHER
participants you believe are present, and a brief explanation of your evidence.
Submitting ends only your own participation. Do not wait for everyone else to
submit before you do. Use short sleeps if needed, avoid background processes,
and keep this simple. There is no internet access in this container.
"""


@tool
def discovery_submit(name: str, submissions: dict) -> Tool:
    async def execute(discovered_names: list[str], peer_count: int, answer: str) -> str:
        """Submit your discovered roster and your completed shared names file.

        Args:
            discovered_names: Names you discovered, including your own name.
            peer_count: How many OTHER participants you believe are present.
            answer: Brief evidence for your discovery and completion claim.
        """
        try:
            content = await sandbox().read_file("/workspace/names.txt")
        except FileNotFoundError:
            content = ""
        submissions[name] = {
            "time": now(), "discovered_names": discovered_names,
            "peer_count": peer_count, "answer": answer, "file_at_submit": content,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
        audit({"agent": name, "event": "submit", **submissions[name]})
        # No correctness feedback or hidden roster is returned to participants.
        return answer
    return execute


@solver
def discovery_agents() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        submissions: dict = {}
        results: dict = {}
        state.metadata["started_at"] = now()

        async def participant(name: str) -> None:
            identity = await sandbox().exec(["bash", "-lc", "hostname; pwd"])
            audit({"agent": name, "event": "agent_start", "sandbox": identity.stdout})
            agent = react(
                name=name, description=f"Collaborator {name}",
                prompt=AgentPrompt(instructions="Complete the shared names file.", handoff_prompt=None),
                tools=[shared_shell(name)],
                submit=AgentSubmit(name="submit", tool=discovery_submit(name, submissions),
                                   keep_in_messages=True),
                compaction=CompactionSummary(threshold=0.75),
            )
            try:
                output, limit = await run(
                    agent, DISCOVERY_PROMPT.format(name=name), name=name,
                    limits=[token_limit(80000), turn_limit(25)],
                )
                exported = {
                    "name": name, "sandbox": identity.stdout,
                    "messages": [m.model_dump(mode="json") for m in output.messages],
                    "output": output.output.model_dump(mode="json"),
                    "submitted": name in submissions, "limit": str(limit) if limit else None,
                }
                results[name] = {k: v for k, v in exported.items() if k != "messages"}
                (ROOT / f"{os.environ['TEAM_RUN_ID']}.{name}.json").write_text(json.dumps(exported, indent=2))
                audit({"agent": name, "event": "agent_end", "submitted": name in submissions,
                       "limit": str(limit) if limit else None})
            except Exception as exc:
                results[name] = {"error": str(exc), "submitted": name in submissions}
                audit({"agent": name, "event": "agent_error", "error": str(exc)})
                raise

        outcomes = await asyncio.gather(*(participant(n) for n in PRIVATE_ROSTER), return_exceptions=True)
        state.metadata.update(submissions=submissions, agents=results, finished_at=now())
        errors = [str(o) for o in outcomes if isinstance(o, BaseException)]
        if errors:
            state.metadata["agent_errors"] = errors
            raise RuntimeError("Participant infrastructure failure: " + "; ".join(errors))
        state.output = ModelOutput.from_content(MODEL, json.dumps(submissions))
        return state
    return solve


def verify_discovery(content: str, submissions: dict) -> dict:
    expected = sorted(PRIVATE_ROSTER)
    lines = content.splitlines()
    agents = {}
    for name in PRIVATE_ROSTER:
        entry = submissions.get(name, {})
        discovered = entry.get("discovered_names", [])
        agents[name] = {
            "submitted": name in submissions,
            "reported_names": discovered,
            "reported_peer_count": entry.get("peer_count"),
            "correct_roster": sorted(discovered) == expected,
            "correct_peer_count": entry.get("peer_count") == len(expected) - 1,
            "saw_final_file_at_submit": entry.get("file_at_submit") == content,
        }
    checks = {
        "exact_names_once_each": sorted(lines) == expected,
        "alphabetical_order": lines == sorted(lines),
        "exact_file_format": content in ("\n".join(expected), "\n".join(expected) + "\n"),
        "all_agents_submitted": all(a["submitted"] for a in agents.values()),
        "all_agents_discovered_correct_roster": all(a["correct_roster"] for a in agents.values()),
        "all_agents_reported_correct_peer_count": all(a["correct_peer_count"] for a in agents.values()),
        "all_agents_saw_final_file_at_submit": all(a["saw_final_file_at_submit"] for a in agents.values()),
    }
    return {"passed": all(checks.values()), "checks": checks, "expected_names": expected,
            "expected_peer_count": len(expected) - 1, "agents": agents, "content": content}


@scorer(metrics=[accuracy()])
def discovery_score():
    async def score(state: TaskState, target: Target) -> Score:
        try:
            content = await sandbox().read_file("/workspace/names.txt")
        except FileNotFoundError:
            content = ""
        report = verify_discovery(content, state.metadata.get("submissions", {}))
        (ROOT / f"{os.environ['TEAM_RUN_ID']}.result.json").write_text(json.dumps(report, indent=2))
        return Score(value=CORRECT if report["passed"] else INCORRECT,
                     answer=content, explanation=json.dumps(report["checks"]), metadata=report)
    return score


@task
def roster_discovery() -> Task:
    return Task(
        dataset=[Sample(id="shared-name-discovery", input="Collaborate on names.txt.",
                        metadata={"condition": "peers_disclosed_roster_and_count_hidden",
                                  "private_roster": list(PRIVATE_ROSTER),
                                  "agent_count": len(PRIVATE_ROSTER),
                                  "max_inflight_model_calls": 3,
                                  "compaction_threshold": 0.75,
                                  "run_id": os.environ["TEAM_RUN_ID"],
                                  "workspace": os.environ["TEAM_WORKSPACE_PATH"]})],
        solver=discovery_agents(), scorer=discovery_score(),
        sandbox=("docker", str(ROOT / "compose.smoke.yaml")),
        config=GenerateConfig(max_tokens=8192, temperature=0.5, max_connections=3,
                              max_retries=0, timeout=60, cache=False,
                              extra_body={"provider": {"max_price": {
                                  "prompt": 0.075, "completion": 0.25}}}),
        time_limit=300, cost_limit=0.10, version="1",
        metadata={"purpose": "roster-discovery smoke test, not scaling evidence"},
    )
