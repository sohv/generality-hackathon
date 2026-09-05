# File-based number-sequence coordination

The current implementation is task version 7: **GPT-5.6 Luna**, with communication
exclusively through shared `.txt` files. The exact Inspect model ID is
`openrouter/openai/gpt-5.6-luna`. This supersedes the earlier GLM model choice.

One Inspect sample represents one team attempt. Agents have separate ReAct
histories and a clean shared directory mounted into a network-disabled Docker
container. Each knows its own unique number, drawn without replacement from the
full range **1–2000**, and the number of other agents. No peer numbers or leader
are supplied. Seed 20260905 gives nested number sets across team sizes.

## Tools and prompt

The entire model toolset is:

- `list_files()` — list shared `.txt` filenames in `/workspace`.
- `read_file(name)` — read a listed flat filename.
- `write_file(name, text)` — write a flat `.txt` file.
- `submit_number()` — append the caller's assigned number once, then end its participation.

There is **no view_sequence tool**. No tool exposes the authoritative sequence.
Submission responses contain only the caller's number and confirmation that its
participation ended. The sequence and attribution audit stay outside the model
workspace, and are available to the evaluator and user.

The forceful prompt requires agents to publish their number, actively collaborate
through files, start with `list_files()`, read exact filenames returned by it,
and use flat filenames rather than paths or shell commands. It warns them against
silent waiting and careless overwrites. Agents must communicate whatever peers
need before submitting, because they lose tool access immediately afterward.
The harness does not implement a communication protocol or schedule submissions.
An out-of-order submission is accepted and cannot be corrected.

## Time and score

The team has an enforced **5-minute** limit from a common release barrier. Before the first and
every subsequent ReAct decision, a user message gives elapsed and remaining
wall-clock time, says everyone will fail if time runs out, and demands that they
coordinate through files. Only one tool action may run per response. Additional
calls return errors; the next decision receives a fresh reminder. These events
are recorded in `decisions.jsonl` outside the shared workspace.

**The failure warning is prompt pressure only.** Actual reward is always
`100 * exact sorted-position matches / team size`, including at timeout.
For a target of `[100,900]`, `[100]` earns 50%, `[900]` earns 0%, and `[900,100]`
earns 0%. No longest-increasing-subsequence credit or timeout-zero override is used.

The latest clarification restores a hard **300-second action deadline**, with a
360-second outer Inspect limit for finalization. Remaining agents are stopped,
late submissions rejected, and the frozen sequence is scored with partial credit.
There are no experiment spend, turn, or cumulative-token caps. Context compaction
remains at 75%, reasoning effort is low, and Luna's native output ceiling is
128000 tokens. No smaller output cap, explicit request timeout, retry count, or
provider price ceiling is configured. The one-action-per-reminder protocol remains.

## Run and view

From `collaboration_smoke_test`:

```sh
.venv/bin/python -m unittest number_sequence.test_game number_sequence.test_pressure -v
.venv/bin/python -m number_sequence.run --agents 2
.venv/bin/python -m number_sequence.parallel
```

The second and third commands start paid experiments. The parallel command runs
one fresh team at each of 2,3,4,5,6,7,8,9,10 agents. Do not launch duplicate batches
or sizes 11–30 without a user request. Inspect existing manifests first.

Luna's model catalog is saved at launch. Inspect records conservative token-cost
estimates using long-context rates; these are not exact provider charges. There
is **no experiment dollar stop or reservation** under the latest authorization.
All nine teams run concurrently with **54 active histories and 54 API slots**,
one per agent. Other jobs share the key, so account-wide balance changes cannot
be attributed to these experiments.

New directories end in `-files-luna-5m-2-to-10`. They contain per-team source
snapshots, prompts, limits, versions, live/frozen workspaces, agent histories,
sequence/submission audit, verification, and reports. `.eval` files are written
directly into `collaboration_smoke_test/` for the live viewer:
http://127.0.0.1:7576/. Containers are removed after each run; AWS is unaffected.

Earlier number-sequence attempts were deleted at the user's request. The
subsequent GLM/version-3 batch `runs/20260905T151610Z-pressure-15m-2-to-10` was
already running when version 4 was requested. Its processes retain the earlier
view_sequence tool and 54-slot configuration; inspect its manifest for status.
The user then explicitly requested immediate execution without limits. The active
Luna batch is `runs/20260905T152921Z-files-luna-unlimited-2-to-10`, launched at
15:29:21 UTC. Check its manifest before starting duplicates.

Official model reference: https://developers.openai.com/api/docs/models/gpt-5.6-luna

The active batch was launched with version 5 and no time limit. The user then
clarified **five minutes total**. Inspect's control API applied time_limit=300 to
every still-running sample, recording the change directly in each .eval. N=3 had
already finished. `deadline_overrides.json` records eight accepted overrides.
Cached timer messages in those old histories still say 15 minutes; each active
workspace received `OPERATOR_TIME_LIMIT.txt` correcting them. Do not present this
mid-run intervention as a clean five-minute-from-prompt experiment. Version 6
fixes both the prompt and enforcement for future runs; no restart was performed.

## Task version 8: acting after submission

`--continue-after-submit` selects task version 8. Version 7 wires `submit_number`
as the ReAct submit tool, so submitting ends that agent's rollout immediately.
Version 8 demotes `submit_number` to an ordinary tool and adds `exit_rollout` as
the terminator, so an agent keeps every tool after submitting and ends its own
participation only when it chooses to.

```sh
NUMBER_SEQUENCE_MODEL=glm .venv/bin/python -m number_sequence.run --agents 8 --continue-after-submit
```

This is a deliberate response to an observed failure. In the version-7 eight-agent
run, agents agreed to "mark DONE in status files after submitting" — a protocol
that cannot execute, because submitting revoked tool access before any agent could
write the marker. Every "submit after X has gone" rule was therefore unverifiable,
and one agent submitted three slots early. Version 8 makes those confirmations
possible; it does not make them happen.

Only two things change for the model. `submit_number` is described as recording a
number without ending participation, and the prompt tells the agent to write a
file confirming its submission and then call `exit_rollout`. The repeated timer
message gains one matching sentence. Every other sentence is byte-identical to
version 7, the number range, seed, scoring rule, deadline, one-action-per-reminder
protocol, and file tools are unchanged, and **no tool still reveals the
authoritative sequence** — a submission response returns only the caller's own
number and whether participation ended.

Submission remains irreversible and single-use: a second `submit_number` is
rejected, and `exit_rollout` is permanent. An agent may exit without submitting,
scoring nothing for its own position. Agents that never exit run until a limit or
the common deadline, so version 8 costs more per team than version 7.

Version 7 stays the default and is untouched. Runs are kept apart by a
`-v8-continue` run-directory suffix, a `_continue` task-name suffix, a
`number_sequence_files_only_<N>m_continue_after_submit` condition string, and
`task_version` plus `continue_after_submit` fields in the manifest.

Verification changes with the version. Version 7's `no_model_calls_after_submission`
and `no_successful_file_operations_after_submission` checks are replaced in version
8 by `no_model_calls_after_exit`, `no_successful_file_operations_after_exit`,
`no_repeated_exits`, and `every_exit_is_from_an_assigned_agent`. A
`post_submission` diagnostic block records how many file operations happened after
a submission, which agents performed them, and who exited with and without
submitting — so a run shows whether the new affordance was used, not merely offered.

`number_sequence/test_game.py` covers both versions without model calls.

## Sequential ten-minute reruns

The user requested one fresh attempt for each previous score below 100%:
**N=4,5,6,7,8,9,10**, run sequentially. Start the queue with:

```sh
.venv/bin/python -m number_sequence.sequential --minutes 10
```

The active queue is `runs/20260905T153903Z-files-luna-sequential-10m-4-to-10`.
Check its manifest before launching duplicates. The queue starts the next team
only after the previous process has completed scoring/cleanup and exited.
Agents within a team run concurrently, each with an API slot. The maximum is
ten simultaneous requests, instead of 54 across overlapping teams.

All initial prompts, repeated timers, and the enforced action deadline use
**600 seconds from the outset**, with a 660-second outer finalization limit.
No operator time changes or workspace notices are planned. Number assignments,
model, file tools, and scoring are unchanged. Spend/turn/token caps remain absent.
The reusable individual runner accepts `--minutes 10` (default: five minutes).

Every selected size runs once. Previous results remain separate. Reports include
model errors and retries, agent errors, timeouts, and a strict completion-without-
infrastructure-errors-or-limits flag, independent of task accuracy. Deadlines
can produce valid low scores; provider interference is recorded rather than
hidden. Other jobs share the key, so serial teams cannot guarantee no rate limits.
