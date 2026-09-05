# Three-agent ClassEval pilot

Run from `collaboration_smoke_test`:

```sh
uv sync --frozen
uv run --with pyarrow python prepare_classeval.py
uv run python run_classeval.py
# Reproduce the earlier unaware prompt condition:
CLASSEVAL_CONDITION=unaware uv run python run_classeval.py
```

The hackathon key stays in the existing ignored `.env`. Only
`openrouter/z-ai/glm-5.3-flash` is permitted by this runner. Each run reserves
$0.50, uses a $0.10 team cost stop plus in-flight calls, and records current
account allowance and model pricing. Account usage deltas can include other
processes; attribute pilot spend using the `.eval` model usage.

This is one deliberately selected task, `ClassEval_39` (`ExpressionCalculator`,
six methods), one team sample, and three concurrent independent ReAct histories.
Selection preceded execution and used the class description and method count;
it was not random and does not establish benchmark difficulty. All histories
start with the upstream system prompt. The current default preserves the upstream
user prompt and appends the short collaboration note from `collaboration_prompt.py`.
No count, roster, roles, or coordination protocol is provided. Set
`CLASSEVAL_CONDITION=unaware` for the earlier byte-identical upstream user prompt
without that note. Both recorded pilots below used the unaware condition.
ReAct's extra system and continuation prompts are disabled. Tools describe local
shell access and submitting `/workspace/solution.py`; no score feedback is supplied.

The default Inspect ClassEval solver generates a whole class in one response.
This adaptation keeps its prompts and tests but adds tools and scores a file.
It is not standard ClassEval pass@k, and is not directly comparable to published
scores. A plain response without tool calls terminates that history without a
submission; the harness does not secretly copy response code into the file.

The initial workspace contains only the exact class skeleton in `solution.py`.
The three histories share one Docker container and working directory, with no
network access. Only that clean directory is mounted. Host attribution labels
are private. Tests, reference solutions, keys, logs, harness code, and project
instructions are outside the participant environment.

Each agent has a 12-turn/150,000-token/five-minute limit and independent context compaction
at 75%. A common ten-minute timeout and cost threshold also apply. Requested
output cap is 32,768 tokens, temperature 0.5, at most three in-flight model calls,
low reasoning effort, a 90-second per-call timeout, and no seed. These bounded pilot limits are not the earlier proposed 5M-token
research allowance. Limits and provider configuration are recorded in the log.

Once all three loops finish, the container is paused, the final file copied,
and every process killed. The copy is evaluated in a fresh network-disabled
container using the original hidden tests and `unittest.main()`. The reference
implementation must pass all tests and the unfinished skeleton must fail before
any paid agent run starts. The primary score is whether the frozen file passes
all tests. Submission status, timeouts, participant errors, and limit exits are
recorded separately; an Inspect execution status of `success` alone is not a
claim of benchmark correctness or error-free participant completion.

The image is the exact upstream ClassEval image digest in `compose.yaml`, with
one CPU and 512 MiB RAM. Runs preserve `workspace/`, frozen `final_solution.py`,
per-agent JSON histories, shell before/after snapshots in `audit.jsonl`, exact
prompts, a manifest, scorer controls, and the result. The live `.eval` is written
in `collaboration_smoke_test/` so the existing Inspect View can find it.

## Provenance

`upstream/class_eval.py` and `upstream/utils.py` are unmodified from
UKGovernmentBEIS/inspect_evals commit
`ac481c7a7b4fb05d6befdfea59b47fc61b839a4f`; the accompanying license is MIT.
The prompt constructor is loaded directly and the system instruction and test
runner strings are extracted from its AST, preserving whitespace.

The dataset revision is `fef204b34e221f207f47904ee660bb920d4c5d1d` of
FudanSELab/ClassEval on Hugging Face. Its parquet SHA-256 is checked during
preparation. Data is CC BY-NC 4.0 and is kept in the ignored `data/` folder.
See https://github.com/FudanSELab/ClassEval for attribution and benchmark details.

Shell snapshots bracket concurrent commands, so a changed before/after snapshot
alone does not prove that command caused the edit. Use the actual commands and
timestamps to reconstruct interference. A successful team file does not prove
collaboration, and a single task cannot estimate a scaling curve.

## Recorded pilot, 2026-09-05

The first attempt, `runs/20260905T121253Z`, reached the ten-minute deadline
without a returned model response or an edit. The original scorer then raised
`KeyError('submissions')`. Its original `.eval`, source snapshot, manifest, and
`failure_report.json` are preserved. No model usage was returned for those
pending calls; absence of usage is not proof of zero billing.

A separate GLM connectivity probe returned in two seconds. A fresh run,
`runs/20260905T122431Z`, used low reasoning effort and a 90-second per-call
timeout. The common-deadline scorer path was fixed and exercised by
`uv run python validate_classeval_timeout.py` without any model calls.

The fresh run completed in 188 seconds. All three agents wrote whole-file
implementations; agents 1 and 2 then made further edits, including another whole
file replacement by agent 2. Two agents submitted. Agent 1 terminated after an
OpenRouter `server_error: The operation was aborted`. One HTTP retry was reported
despite the requested `max_retries=0`; retain that observed discrepancy.

The final file passed 35/37 tests, failing `test_transform_5` and
`test_transform_6` (unary-minus normalization). Its ClassEval all-tests-pass
score is **0**. The first whole-file writes were independently evaluated after
the run: agent 1 passed 24/37, agent 2 passed 19/37, and agent 3 passed 23/37.
These are diagnostic snapshots from a concurrent run, not isolated baselines.
No communication files appeared; the workspace contains only `solution.py`
and Python bytecode cache files. Do not infer an agent's awareness from that
absence or interpret the final score as proof of collaboration.

The main run's reported model cost is $0.0049734, plus $0.00000445 for the
connectivity probe. The account balance declined by $0.023215555 across the
whole period; failed requests and other processes may account for the difference.
Do not attribute that whole account delta to this pilot without provider billing
records. The first failed attempt's usage remains unknown.

`uv run python verify_classeval.py classeval/runs/20260905T122431Z` verified
the actual model inputs: exact upstream system/user prompts, neutral tools,
separate tool histories, three private agent spans, and one container. It also
checked that the scored frozen file equals the preserved workspace file. There
were zero compactions. Agent 1's partial history was recovered from its `.eval`
span after the API exception and is explicitly marked as reconstructed.

The completed log is
`../2026-09-05T12-24-33-00-00_classeval-shared_8P9JidaX88BK8C7hhdbG4J.eval`.
See `runs/20260905T122431Z/result.json`, `verification.json`,
`first_write_scores.json`, and `workspace/solution.py` for the artifacts.
