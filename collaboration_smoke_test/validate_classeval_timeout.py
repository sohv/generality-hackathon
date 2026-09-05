"""Exercise Inspect's common-deadline scoring path without any model calls."""
import asyncio
import json
import os
from pathlib import Path
from tempfile import mkdtemp

from dotenv import dotenv_values
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.solver import solver
from inspect_ai.util import sandbox

from classeval_team import BASE, RECORD, final_artifact
from smoke_team import MODEL, ROOT

@solver
def expire_before_submission():
    async def solve(state, generate):
        identity = await sandbox().exec(["hostname"])
        state.metadata["container"] = identity.stdout.strip()
        await asyncio.sleep(10)
        return state
    return solve

def main():
    os.environ["OPENROUTER_API_KEY"] = dotenv_values(ROOT / ".env")["OPENROUTER_API_KEY"]
    directory = Path(mkdtemp(prefix="timeout-validation-", dir=BASE / "runs"))
    workspace = directory / "workspace"
    workspace.mkdir()
    (workspace / "solution.py").write_text(RECORD["skeleton"])
    os.environ.update(CLASSEVAL_RUN_DIR=str(directory), TEAM_WORKSPACE_PATH=str(workspace))
    logs = eval(Task(name="classeval_timeout_validation", dataset=[Sample(input="Harness validation; no model call.")],
                     solver=expire_before_submission(), scorer=final_artifact(), time_limit=2,
                     sandbox=("docker", str(BASE / "compose.yaml"))),
                model=MODEL, log_dir=str(directory), display="plain")
    log = logs[0]
    assert log.status == "success" and not log.samples[0].error
    assert not log.stats.model_usage
    assert (directory / "final_solution.py").read_text() == RECORD["skeleton"]
    result = json.loads((directory / "result.json").read_text())
    assert result["outcome"] == "fail" and not result["all_submitted"]
    print("PASS: common deadline freezes and scores the artifact with absent submission metadata; no model calls.")

if __name__ == "__main__":
    main()
