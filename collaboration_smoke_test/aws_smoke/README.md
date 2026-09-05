# AWS names smoke test

One Inspect sample is an entire team attempt. Ten independent GLM 5.3 Flash
ReAct histories run on the laptop, each with its own private name. Their local
stdio MCP servers use the same SSH Docker context and container ID to access
one `/workspace` on AWS. Each model sees `list_files`, `read_file`, `write_file`,
and `submit`; tools operate only on flat `.txt` files. The container has no
network or host mounts. The task, scorer, audit trail, keys, and `.eval` stay
on the laptop. This demonstration does not expose arbitrary shell execution.

Each prompt names only that participant, asks for all participant names once
in alphabetical order, and ends with the exact note in
`../collaboration_prompt.py`. No roster, count, roles, or messaging protocol
is supplied. Model inference uses OpenRouter; the task VM does not host model
weights. This is one shared container per team attempt, not linked Inspect runs.

## Current limits and scoring

The default is 200 turns, 5M cumulative tokens, and 30 minutes per agent,
with independent context compaction at 75%. The team deadline is 31 minutes.
There is a $1 cost stop and a $2.50 reservation, including bounded concurrent
calls. Only the hackathon key in `../.env` and GLM 5.3 Flash are used.

An individual submission ends that agent's loop. Once all loops have submitted
or stopped, the container is paused and the final workspace exported before
scoring. **The score depends only on the final `names.txt`**: all expected names
exactly once, in alphabetical order, one per line, with an optional trailing
newline. It does not use the last agent's reply or require correct individual
submissions. Submitted rosters and peer counts remain diagnostic fields.

The source, exact prompts, versions, prices, limits, and AWS deployment are
recorded per run. `verification.json` independently checks actual model inputs,
private histories, container isolation, concurrent calls, and the scored file.
This is a smoke test, not evidence of a scaling law.

## Running and cleanup

Use the personal AWS `hackathon` profile in eu-west-2. `provision.py` creates
one tagged t3.small VM and a security group permitting SSH only from the
laptop's public IP. **The current default keeps the VM running with no shutdown
timer**, as requested by the user. Root disk deletion is enabled for eventual
termination. Individual task containers are still exported and removed after
each run, leaving the host ready for another team attempt.

From `collaboration_smoke_test`, with the `collaboration-names-aws` SSH alias
pointing to the current deployment's public IP:

```sh
.venv/bin/python -m aws_smoke.run_names --context collaboration-names-aws --agents 10 --turns 200
.venv/bin/python -m aws_smoke.verify_run aws_smoke/runs/RUN_TIMESTAMP
```

The legacy `run_and_cleanup` entry point also honors the current deployment's
`keep_running_after_eval` flag. Do not terminate this VM until the user asks.
When removal is requested, `.venv/bin/python -m aws_smoke.cleanup_aws` checks
the recorded instance identity and tags, terminates it, and deletes its security
group. The older user VM remains stopped with its disk preserved.

`provision --replace-terminated` permits a new host only after verifying the
recorded predecessor is terminated and its security group was deleted. Previous
deployment records are archived locally. An optional `--auto-terminate-minutes`
flag exists for future disposable runs, but requires renewed user authorization.

## Recorded runs

The first AWS run, `runs/20260905T130207Z`, had a 20-turn limit and the older
rule requiring both the final file and every individual submission to be
correct. It finished in 88 seconds, cost $0.0029188 in logged model usage,
and had peak model concurrency 10. The final alphabetical file contained six
of ten names. Eight agents submitted incomplete rosters and two hit the turn
limit. Its historical score remains 0; final-file-only scoring would also fail.
Its VM and security group were deleted after workspace export.

Local and remote deterministic `validate_mcp` runs verified transport without
model calls. These scripted transport checks are not agent collaboration
results. The external exploit-generation repository was not modified or run.

A later startup attempt stopped at budget preflight before any model call:
`runs/startup-failure-20260905T1316Z/failure.json`. Its disposable VM was removed.
The model advertises a 1,310,720-token context, so the current $2.50 reservation
covers the $1 stop plus ten maximum-size calls already in flight. This is a
reservation, not the expected charge. Account balance deltas may include other
processes; use logged model usage for run attribution.

The 200-turn rerun, `runs/20260905T132042Z`, finished in 164 seconds. The final
file contains eight names, missing Mira and Zara, so its final-file-only score
is 0. Nine agents submitted; Mira encountered an OpenRouter server error,
"The operation was aborted." No agent hit the turn, token, time, or cost limit.
There were 176 model calls, at most 29 for one agent, peak concurrency 10, and
zero compactions. Logged model cost was $0.00731026. All infrastructure checks
passed. Mira's partial JSON history is explicitly reconstructed from the input
to its failed model call in the original `.eval`. The VM remains running.
