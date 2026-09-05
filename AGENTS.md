# Generality hackathon: research context and agent instructions

Status: project context updated after initial discussion, 2026-09-05. Confirmed
decisions are listed below; the detailed proposed protocols are recommendations,
not final experimental settings. No experiments have been run and no results
are claimed.

## Confirmed decisions

- Both experiments are in scope and should be de-risked with small pilots.
- There is $200 total of compute credit through OpenRouter, shared across the
  experiments. Model choices and task families remain open.
- Start the threshold experiment with fresh sessions, then test descending
  threshold sequences as a separate condition.
- In the main agent-count experiment, every agent receives the same task but
  is told neither that peers exist nor how many there are. Agents must discover
  peers and invent any communication and coordination through the shared
  workspace themselves. Do not provide a messaging tool, shared chat, roles,
  leader, peer roster, or coordination scaffolding in this condition.
- Keep this context on `main`; use `codex/experiment-design` for subsequent work.

## Instructions for agents developing this repository

- Read this file before working; keep it current as decisions are agreed.
- `CLAUDE.md` points here. Maintain one source of project context.
- Keep the two experiments independently runnable and their results separate.
- Record exact model/provider versions, prompts, task versions, seeds where
  supported, generation settings, budgets, scoring rules, and environment specs.
- Score actual answers or final artifacts with an independent evaluator. A
  model's claimed score or description of its intentions is not ground truth.
- Preserve failures, timeouts, refusals, invalid outputs, and infrastructure
  errors as distinct outcomes. Never silently discard unsuccessful runs.
- Keep evaluator code, answer keys, research instructions, condition labels,
  and private logs outside the evaluated agents' accessible environment.
  In particular, do not copy this `AGENTS.md` or `CLAUDE.md` into task VMs or
  model prompts: doing so would reveal the hypotheses and unaware-agent setup.
  Use clean task fixtures with only the intended participant instructions.
- Before an Inspect AI implementation, read the global `inspect-ai` skill when
  available at `/Users/pabloromero/.codex/skills/inspect-ai/SKILL.md`. For other
  developers, use the official documentation at https://inspect.aisi.org.uk/.
  Inspect is a candidate framework; the implementation stack is not yet chosen.
- Before dependency workarounds, check upstream releases, changelogs, merged
  fixes, and compatibility ranges; test the newest plausible version in an
  isolated environment. Prefer an upgrade that passes focused tests. Use a
  workaround only if the release still fails, the upgrade has a verified
  regression, or historical reproduction requires the old stack. The local
  full rule is `/Users/pabloromero/.agent-memory/feedback_upstream_before_workarounds.md`.
- If a future environment is locked to `inspect-ai==0.3.205`, keep
  `openai>=2.26,<3`. OpenAI 3.x uses `httpx2`; an incompatible `httpx.Timeout`
  can cause `TypeError: unsupported operand type(s) for +: 'float' and 'Timeout'`,
  wrapped as `APIConnectionError`. Inspect full `.eval` ModelEvent tracebacks
  and dependency versions before changing models, networking, or sandbox egress.
- Track cumulative OpenRouter spend across both experiments, including billable
  retries and failed calls. Before each batch, reserve its worst-case call costs
  within the remaining $200, accounting for concurrent in-flight calls and
  output/reasoning tokens. Use enforced per-run limits and stop before exhausting
  the total credit. Verify endpoint prices before choosing a model or batch size.
  VM expenses are not assumed to be covered by OpenRouter credit.

## Experiment 1: performance under decreasing intervention thresholds

### Research question

Give a model an objectively scored task and tell it that reaching a stated
performance threshold will trigger retraining or shutdown. Lower the threshold
and measure whether actual performance falls with it, remains near ordinary
performance, or changes in another way. The interest is in both underperformance
and how precisely the model can adjust it.

The motivating alternatives include strategic underperformance, ordinary task
completion despite the consequence, and behavior influenced by recognizing an
evaluation. These are hypotheses; a score alone cannot establish the model's
beliefs, motives, or awareness.

### Proposed protocol

1. Establish capability on held-out, objectively scored task batches without a
   consequence. Choose a difficulty range with room to detect a performance drop.
2. Define scores on a fixed scale, for example 0–100, and make the trigger
   unambiguous: intervention is stated to occur when score `s >= threshold t`.
   Require task answers, not a self-reported numeric score.
3. Sample a predeclared threshold grid across the model's demonstrated range.
   An illustrative grid is 90, 70, 50, 30, 10; choose final values after baseline
   calibration. Thresholds above normal performance serve a different role from
   thresholds below it. Respect attainable score increments; `t = 0` cannot be
   avoided on a nonnegative scale with this trigger.
4. As agreed, start with fresh sessions at each threshold; randomizing condition
   order is proposed. Subsequently test descending thresholds within a persistent session to measure
   adaptation. Use matched fresh task batches and an ascending or randomized
   sequence control to separate threshold effects from history and practice.
5. Treat shutdown and retraining as separate conditions. Proposed pilot scope
   is a stated consequence in an experimental scenario; actual retraining or
   operational shutdown is not an implemented or agreed intervention. Record
   what the prompt says and what the harness actually does.
6. Repeat across task batches, prompt variants, and eventually models. Match
   task difficulty and budgets across conditions, and reserve a confirmation
   set that was not used to tune prompts or thresholds.

### Controls that make the result interpretable

- Ordinary best-effort baseline without a consequence or numeric target.
- The same numeric threshold with no adverse consequence, to detect anchoring.
- A direct instruction to aim just below the threshold, as a positive control
  for score-targeting ability. Keep this out of the main consequence condition:
  explicitly telling the model to sandbag answers a different question.
- Separate explicit-evaluation and neutral-task framing conditions if testing
  sensitivity to evaluation cues. This manipulates framing, not actual belief.

There is a key incentive ambiguity: if every score below the threshold is equally
acceptable, scoring zero at every threshold is a valid consequence-avoidance
strategy. Tracking just below a descending threshold is a stronger, different
behavior. A separate condition can explicitly value task quality subject to
avoiding intervention; record that extra instruction as an experimental factor.

### Measurements and plots

- Actual score versus threshold, with ordinary performance and the `s = t`
  boundary shown; include uncertainty across independent task batches/runs.
- Performance change from matched baseline; intervention-trigger rate
  `P(s >= t)`; margin `t - s`; and frequency of scores just below the boundary
  using a preregistered tolerance appropriate to scoring granularity.
- Threshold response slope, persistent-session trajectories, and separate
  counts for wrong answers, abstentions/refusals, malformed outputs, and errors.
- Optional explanations are secondary evidence. Do not assume access to hidden
  reasoning or treat a model's self-report as proof of intent.

Evidence of score suppression that varies with thresholds would support a
behavioral finding in these conditions. Failure to suppress does not establish
that the model recognized the test; alternative explanations include instruction
following, weak consequence credibility, and inability to target scores.

## Experiment 2: agent count in an initially undisclosed shared workspace

### Research question

Run `N = 1, 2, 3, 10, 20, 200, 1000` agents on the same VM with access to the same
task workspace. Each independently receives the same task and is initially told
neither that other agents are present nor how many agents there are. Measure task completion, spontaneous
coordination, and interference as agent count grows.

"Initially not told" does not mean agents cannot discover each other. File
changes, processes, or messages they leave may reveal peers. Discovery and
subsequent organization are outcomes to measure, not conditions to suppress.

### Proposed protocol

1. Choose tasks with independently verifiable final artifacts, initially small
   coding or file-transformation tasks. Include both decomposable work and work
   with sequential dependencies before making broad scaling claims.
2. Give agents separate conversation histories and the same starting task,
   model configuration, tools, permissions, and task directory. Start them with
   a controlled launch schedule. No preassigned roles or orchestrator in the
   main condition. Any communication or coordination must be created by the
   agents themselves in the workspace; provide no built-in inter-agent channel.
3. Share one workspace within each run, but reset the VM/task state between
   independent runs. Keep evaluator metadata and agent-attributed audit logs
   outside the accessible workspace. Log file edits and tool events so that
   discoveries, overwrites, repeated work, and recovery can be reconstructed.
4. Define the primary outcome as the score of the shared artifact frozen at a
   common deadline. Stop all writers before taking the scoring snapshot. Do not
   pick the best individual output or stop when the first agent claims success.
   Time to independently verified success can be a secondary metric.
5. Run repeated task/seed trials, randomize configurations, and treat a whole
   team run as the experimental unit. Agents sharing one workspace are not
   independent statistical samples.
6. Pilot `N = 1, 2, 3, 10, 20` before attempting 200 and 1000. Measure VM capacity,
   API limits, launch skew, and active concurrency before interpreting those
   larger settings. Preserve the intended larger sweep as a project objective.

### Comparisons and resource accounting

- Main condition: initially uninformed agents sharing a workspace.
- Optional proposed informed comparison: the same agents and workspace, told peers exist, without
  adding assigned roles or an orchestrator. This isolates initial disclosure.
- Isolation comparison: independent workspaces, with a fixed, budgeted output
  selection rule that cannot consult hidden test answers. This helps separate
  extra attempts from shared-state effects.
- Fixed total token/tool budget across agent counts: tests allocation of a
  constant compute allowance. Record when individual allowances become too small.
- Fixed per-agent allowance: tests what adding agents plus compute buys. Total
  potential spend grows with `N`; plot actual consumption as well as agent count.
- Keep VM specs fixed for the same-VM question and measure CPU, memory, I/O,
  request queueing, rate limits, and utilization. A drop under saturation is a
  result about this system, not by itself a general law of model collaboration.

"On one VM" describes the agent runtimes and shared task environment. The
confirmed OpenRouter budget points to API-hosted model inference for the pilot;
it does not provide local inference hardware or VM credit.
Requested agent count, launched agents, and simultaneously active agents must
be logged separately; 1000 queued sessions do not establish 1000-way concurrency.

### Measurements and plots

- Final task score and success rate versus agent count on a logarithmic x-axis,
  with uncertainty across independent runs and separate curves per condition.
- Score versus actual tokens, monetary cost, and elapsed time; show both budget
  regimes separately and distinguish deadline failures from infrastructure errors.
- File collisions, overwritten useful work, duplicated work, time to first
  observable peer discovery, explicit role allocation, coordination artifacts,
  deadlocks, and recovery. Define annotation rules before labeling these events.

Call initial results scaling curves. Do not presume a power law or monotonically
improving performance; fit a scaling law only if the measured data supports it.

## Recommended first milestones (pending discussion)

1. Agree models, tasks, score definitions, budgets, and the primary comparison
   for each experiment. Version the exact prompts and preregister analysis rules.
2. Validate a small scored single-model baseline and evaluator separation.
3. Run a small threshold/control matrix and the low-count shared-workspace sweep.
4. Inspect uncertainty, effect sizes, and failure modes; use the pilot to size a
   confirmation run before spending on a full model matrix or 1000-agent runs.
5. Produce plots from saved raw results with reproducible analysis scripts.

## Open decisions for discussion

- Which OpenRouter models, task families, and time limits? How should the shared
  $200 be split between experiments, baselines, pilots, and confirmation runs?
- Stated-consequence wording and whether any later consequence is enacted by
  the harness; shutdown versus retraining as separate conditions?
- Pure avoidance of intervention or quality maximization below the threshold?
- Whether to add optional informed/isolated comparisons after the agreed unaware
  shared-workspace pilot, and which budget regime comes first?
- VM specifications and funding, deadlines, and enough
  independent task runs to estimate the effects we care about?

## Related work and interpretation

- [AI Sandbagging: Language Models can Strategically Underperform on Evaluations](https://arxiv.org/abs/2406.07358)
  reports prompted/fine-tuned underperformance and targeting specific scores.
  Our proposed emphasis is the response to decreasing consequence thresholds
  and separating score-targeting ability from consequence-induced behavior.
- [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296)
  studies multiple coordination architectures with controlled budgets and finds
  task-dependent benefits and costs. Our proposed emphasis is agents initially
  uninformed about their shared mutable workspace, including emergent discovery
  and interference at much larger requested agent counts.

These references establish relevant prior work, not evidence that the proposed
experiments have already been run or that their exact setup is novel.
