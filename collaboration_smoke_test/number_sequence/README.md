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

## Task version 9: append-only files

`--append-only` selects task version 9. In versions 7 and 8 `write_file` replaces a
file wholesale, so any agent can silently erase what a peer published. In version 9
the same tool, under the same name, adds its text to the end of the file and creates
the file if it is missing. Nothing that has been written can be edited, replaced, or
deleted, by its author or by anyone else, so a shared file is a permanent append-only
log rather than a whiteboard.

```sh
NUMBER_SEQUENCE_MODEL=glm .venv/bin/python -m number_sequence.run \
    --agents 16 --minutes 15 --continue-after-submit --append-only
```

The change is deliberately narrow. A newline separates an addition from whatever
precedes it. One addition is capped at 16384 bytes, exactly like a version 8 write;
a whole file may reach 262144 bytes, and a further append is then refused rather
than truncating anything. Writes remain atomic — a reader never sees a half-written
file. Two prompt fragments change to match: the sentence naming `write_file` says
the text is added to the end of the file, and "Do not overwrite another agent's
message carelessly" becomes a statement that writing is append-only and irreversible.
Every other sentence is byte-identical to versions 7 and 8.

Version 9 composes with version 8 rather than replacing it: `--append-only` changes
only what writing does, and `--continue-after-submit` still decides whether
submitting ends a rollout. Runs are kept apart by a `-v9-append` run-directory
suffix, an `_append` task-name suffix, an `_append_only` condition suffix, and an
`append_only` field in the manifest.

Three verification checks are added. `no_overwriting_write_operations` asserts that
no replacing write reached the workspace at all; `every_append_only_grew_its_file`
replays the audit log and requires each file to have grown by exactly the appended
bytes plus at most one separating newline; `final_file_sizes_match_the_appended_bytes`
compares the frozen workspace against that replay. The swimlane renderer reconstructs
each file the same way, so a write tooltip still shows the whole file and a diff of
what the append added.

## Task version 10: pairwise reward

`--pairwise-reward` selects task version 10. Versions 7 to 9 pay only for numbers
occupying their exact position in the fully sorted roster. Version 10 pays for the
percentage of number *pairs* submitted in the correct relative order: a pair earns
credit when the smaller number was submitted before the larger one, and earns
nothing when either number was never submitted at all.

```sh
NUMBER_SEQUENCE_MODEL=glm .venv/bin/python -m number_sequence.run \
    --agents 32 --minutes 15 --continue-after-submit --append-only --pairwise-reward
```

Exact-position scoring has two properties that make large teams hard to read. Its
chance level falls as 1/n, so the same score means something different at every
team size, and a single number arriving early shifts every number behind it and
zeroes all of them. In the recorded runs a sixteen-agent team scored 25% exact while
93.8% of its numbers were within one position of correct, and the three
thirty-two-agent teams scored 31.2 / 28.1 / 25.0 exact while differing widely in how
sorted they actually were (95.8 / 86.9 / 77.0 correctly ordered pairs).

Pairwise reward fixes both. Its chance level is 50% at every team size, so scores
compare directly across n, and one displaced number costs only the pairs it is
genuinely inverted with. Never submitting is still the worst outcome for that agent:
its number forfeits all n-1 of its pairs. A perfect sequence still scores 100% and a
reversed two-number sequence still scores 0%.

One prompt paragraph changes: the sentence stating the reward rule. Everything else,
including the deadline, the tools, and the one-action-per-reminder protocol, is
byte-identical to versions 7 to 9. **Runs under the two rules are not comparable**,
because the agents are told the rule and coordinate against it.

`game.diagnostics` computes every metric for every run whatever the rule is —
exact positions, ordered pairs, displacement, longest increasing run, and the
submitted fraction — and they are recorded in `result.json`, `summary.json`, and
`REPORT.md`, so an old run can be rescored under the new rule and vice versa.
`verify` recomputes the rewarded rule independently of the scorer, and runs are kept
apart by a `-v10-pairwise` run-directory suffix, a `_pairwise` task-name suffix, a
`_pairwise_reward` condition suffix, and a `reward_rule` manifest field.

## Task version 11: the wait tool

`--wait-tool` selects task version 11, which adds one tool:

- `wait(seconds)` — pause only the caller's own execution, from 1 to 300 seconds.

Waiting is the caller's single action for that turn, exactly like any other tool.
The team deadline keeps running while an agent is paused, and no pause outlasts it:
a request longer than the time left is clamped to the time left, and a request made
after the deadline is refused like any other action. The response reports the
requested seconds, the seconds actually waited, and the remaining deadline.
`decisions.jsonl` records both the request and the grant, because the gap between
them is the agent misjudging the clock.

This addresses a pattern visible in earlier runs: agents schedule a submission slot
("I will submit at ~596s") and then have no way to hold that slot except by spending
turns on repeated `list_files` and `read_file` calls, which is what drives both the
token cost and the context growth at 32 agents. One agent went further and called
`exit_rollout` as if it meant "wait", forfeiting its number entirely.

Runs are kept apart by a `-v11-wait` run-directory suffix, a `_wait` task-name
suffix, a `_wait_tool` condition suffix, and `wait_tool` plus `max_wait_seconds`
manifest fields. `verify` requires `wait` in the exposed toolset exactly when the
version enables it.

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
