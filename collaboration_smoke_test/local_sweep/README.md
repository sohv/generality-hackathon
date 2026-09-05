# Local names sweep: 2 through 1024 agents

The current parallel batch is `runs/20260905T140226Z-parallel`. Two earlier
serial starts are preserved as interrupted pilots and excluded from the sweep.
This batch is complete: all ten frozen-file scores passed independent checks,
with $1.57742560 in logged model cost. Read its `REPORT.md` for results and
stopping reasons, including the intervention affecting the two largest teams.
The user asked to execute team sizes in parallel, so `parallel.py` owns the
budget lock and launches ten separate Inspect child processes. The slot
allocations for the ten ascending team sizes are 2, 4, 8, 16, 16, 16, 16, 16,
16, and 18, totaling 128. These are static allocations; unused slots from a
finished team are not reassigned mid-run. Queuing and concurrent team workloads
therefore affect runtimes and potentially scores.

The requested sweep has ten team attempts: 2, 4, 8, 16, 32, 64, 128, 256,
512, and 1024 agents. The single-agent condition was removed at the user's
request. There is one Inspect sample and one `.eval` per team size, not an
evaluation per agent. Each run uses a fresh shared directory and one local
Docker container with that directory mounted as `/workspace`.

All agent histories are prepared before a common release barrier. GLM 5.3
Flash requests use at most 128 API connections, as approved by the user.
Large teams therefore queue model requests. All histories remain independent;
no MCP process is launched per agent. Local bounded file tools implement the
same list/read/replace operations against the mounted workspace. This transport
differs from the earlier AWS MCP runs and should be treated as a separate
experimental condition. The persistent AWS VM is not used or modified.

Only the clean workspace is mounted. The roster, prompts, scorer, credential,
audit, source snapshots, and logs remain outside it. Each agent receives one
private, unique, eight-letter pronounceable pseudonym. A seeded host-side pool
of 1024 names gives nested rosters across sizes; it contains no exposed indexes
or total count. All 1024 names fit within the unchanged 16 KiB file-write cap.
The task prompt and minimal collaboration note match the earlier names test.

## Score

`coverage_percent = 100 * unique expected names present / expected team size`.
Read one name per line, trim surrounding whitespace, and ignore empty lines.
Names must match the expected spelling and case. A repeated name counts once;
invented names earn no credit. Alphabetical order, duplicates, and unexpected
names are recorded separately and do not lower this requested coverage score.
The final shared file is scored after every agent has submitted or stopped.
Individual agent submissions do not determine the score.

Scorer controls verify 8/10 = 80%, duplicate/invented entries give no extra
credit, an empty file scores 0%, and a reversed complete roster scores 100%
coverage while failing the separate alphabetical diagnostic.

## Budget and limits

The user approved a $25 total cap and 128 simultaneous model calls. The
parallel batch allocates $24.56, leaving $0.44 for the two interrupted pilots
and their conservatively reserved uncertain calls. Parent allocations sum to
that total; each child checks its allocation before bypassing the parent-owned
budget lock. The runner
checks the hackathon key and prices and holds the repository budget lock.
Before each team, it leaves headroom for all maximum-size in-flight calls,
and deducts known prior spend plus conservative reservations for calls that
returned no usage. This can stop a batch before every size if the remaining
verified allowance is insufficient; stopped sizes must be reported explicitly.
Other processes using the key are not controlled by this lock.

Per-agent limits remain 200 turns, 5M cumulative tokens, and 30 minutes. The
team deadline is 31 minutes. Generation uses 8192 maximum output tokens,
temperature 0.5, low reasoning effort, no requested retries, and a 60-second
attempt timeout. Independent compaction is enabled at 75% of context.

From `collaboration_smoke_test`, the current coordinated batch entry point is:

```sh
.venv/bin/python -m local_sweep.parallel
```

Do not rerun it to view results: it starts a fresh paid batch. The current
batch directory is printed at startup. `.eval` logs are written directly into
`collaboration_smoke_test` and can be watched with the existing Inspect View.
Each batch has `summary.csv`, `summary.json`, `REPORT.md`, and a manifest;
each `nNNNN` directory has its frozen workspace, individual histories,
audit, prompt/source provenance, results, and independent verification.

The read-only plot command can use an ephemeral plotting environment without
changing the Inspect runtime:

```sh
uv run --no-project --with matplotlib --python 3.12 python local_sweep/plot.py local_sweep/runs/BATCH_TIMESTAMP
```

This writes PNG, SVG, and PDF plots. One repetition per size provides exploratory
data, not a power law or reliable uncertainty estimate. API failures, startup
skew, queuing above 128 agents, early submissions, and overwrite collisions
are potential contributors to observed coverage. Keep them visible.

`summary.csv` records the API slots allocated to each completed team. Optional
`analyze_writes.py CHILD_BATCH_DIRECTORY` reconstructs names-file coverage after
each successful write and counts writes that removed expected names.

## Timing interpretation

Inspect 0.3.263 ModelEvent timestamps include time waiting for a connection.
Raw overlap counts queued generations. `correct_timing.py PARALLEL_BATCH`
adds `timing.json` per completed team and corrects the summary's `api_peak`
to an estimate from completed minus working_time through completed. This
approximates successful request intervals; errors without completion are
excluded. The raw pending peak is preserved separately. The 32-agent team had
32 pending calls but a successful-request peak estimate of 16, matching its
16 configured slots. Do not infer API concurrency directly from pending spans.

The two largest-team processes were paused for about a minute during the
parallel batch to investigate the shared key balance. The user confirmed other
jobs were using the same key. The pause triggered request timeouts for 16 agents
at N=512 and 17 at N=1024; these are recorded as operator-pause timeouts rather
than provider failures. Their durations and agent deadlines include the pause.
See `operator_events.json`; do not treat these as uninterrupted trials.

After the coordinator exits, `.venv/bin/python -m local_sweep.report BATCH_PATH`
recomputes frozen-file scores, consolidates timing and stopping diagnostics,
and writes the final report. It performs no model calls. Then regenerate the
plots with the command above. Account-wide balance changes include the user's
other jobs and must not be presented as this sweep's model spend.
