# Three-agent collaboration smoke test

From the repo root, first run `cd collaboration_smoke_test`, then
`uv run python run_smoke.py`. Only
`openrouter/z-ai/glm-5.3-flash` is allowed by the runner. It reads the hackathon
key from `.env`, which is git-ignored and never mounted in Docker.

Run `uv run inspect view --log-dir . --port 7576` to follow live logs.
The `.eval` files, per-agent JSON histories, audit JSONL, result JSON, and
manifest are written into `collaboration_smoke_test/`. The shared files live in
a new `team-workspace-<UTC timestamp>/` directory inside that same folder.

Existing `.eval` logs, audit trails, and run reports were moved without editing
their contents. Absolute paths recorded inside historical logs refer to the
original run locations; those files now sit under `collaboration_smoke_test/`.
New runs resolve paths from the scripts' current location automatically.

One team sample launches Ada, Bruno, and Cleo concurrently using
`asyncio.gather` and Inspect `agent.run`. Each has a separate conversation.
All shell calls inherit the same sample sandbox and run in `/workspace`.
That is one shared Docker container in Docker Desktop's Linux VM. There is
no linking of separate eval runs and no merging of conversation histories.

Agents introduce themselves and acknowledge their teammates through files,
collaborate on `collaboration.txt`, and each call their own submit tool.
One agent submitting ends only that agent. Scoring happens after all three
loops finish. Host-side scoring checks the artifact, all three submissions,
and that each submission observed the final file. Communication behavior
and authorship are checked against the individual transcripts/audit trail.

This is an explicitly informed, named-agent infrastructure test. It is not
the main initially-unaware condition and provides no scaling evidence.
No external message board is supplied in this test.

The pinned base image is already present locally. Only the clean task
workspace is bind-mounted; the harness, logs, key, and AGENTS.md remain
outside the participant environment. Container networking is disabled.
The container is cleaned up after the run; shared files remain on the host.

The test reserves $0.50 against current key allowance, stops the team at a
$0.10 reported-cost threshold (with headroom reserved for in-flight calls),
allows at most 3 concurrent model requests, sets `max_retries=0`, and limits
each agent to 20 turns/50,000 cumulative tokens and the team to 300 seconds.
OpenRouter endpoint price ceilings are enforced. The API/model preflight
uses the same model and creates a separate, clearly named `.eval` file.

## Completed run

`smoke-20260905T113819Z` passed in 88 seconds. All agents contributed their own
line, communicated through notes, and submitted the same final artifact hash.
The saved log has three named agent spans and 21 model generations. Inspection
of every model input confirmed that tool results never crossed conversation
boundaries; shared knowledge came through the filesystem. All three agents
reported container `c6f923dbe000` and working directory `/workspace`.

Logged cost: $0.00365358 for the team; $0.00365928 including preflight.
The log reports one model retry despite the configured `max_retries=0`; the
verification JSON preserves that observation. This prototype's reservation
logic should be hardened before use for large or concurrent batches.

The current smoke test uses default ReAct context handling without compaction.
For long runs, each independently constructed `react(...)` can receive
`compaction=CompactionSummary(threshold=0.75)` (import from `inspect_ai.model`).
This compacts that agent's own conversation at 75% of its model context window;
it does not compact or reset the shared filesystem. The cumulative token
allowance is a separate limit and must be sized for the longer run.

## Private-name discovery variant

Run `uv run python run_smoke.py --discovery`. The implementation is
`discovery_team.py`. It launches five independent ReAct agents, but each prompt
contains only that agent's own name. It discloses that collaborators exist;
their names and count stay in the host-side evaluator. The initial task
workspace is empty. Participants choose their own communication files.

The target is `names.txt`, with every participant's name exactly once, one per
line, alphabetically sorted, with no header. Each submit must separately report
the discovered names and number of other participants. The scorer compares all
claims with the hidden roster, and verifies that every agent saw the same final
file. It supplies no correctness feedback during the run. Compaction at 75% is
enabled independently for each agent, although the short test should not need it.

Five agent loops run concurrently with at most three simultaneous model
requests. Each has a 25-turn/80,000 cumulative-token allowance; the common
deadline is 300 seconds. This is a discovery/coordination smoke test, not a
claim that five simultaneous inference requests ran or that collaboration scales.

Run `smoke-20260905T114619Z` passed in 225 seconds, costing a logged
$0.006335805 including preflight. Every agent reported the full roster and four
peers. The final file contains Arun, Felix, Lena, Mira, and Zara in that order.
`smoke-20260905T114619Z.verification.json` records all checks, including inspection
of actual model inputs for private initial identities, separate tool-result
histories, and the common sandbox identity. There were 54 model generations,
zero compactions, and five tool errors recovered from during the run.
