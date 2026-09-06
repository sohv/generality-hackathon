"""Flatten one team run into a single chronological JSONL event stream.

Each agent's own history shows only what that agent did. This reads the .eval
log instead and interleaves every agent's actions on one wall-clock timeline,
so a run can be read globally: who wrote which file while who else was reading
it, and what each agent was thinking when it acted.

    python -m number_sequence.extract_events RUN_DIRECTORY
    python -m number_sequence.extract_events path/to/run.eval --output events.jsonl

Emitted record types:

  tool_call    one tool invocation: arguments, result, error, and the reasoning
               and visible text of the model response that produced it
  message      a model response that called no tool, so its visible output and
               reasoning are not attached to any tool_call
  model_error  a failed model request (rate limits, provider errors), which is
               usually what explains a silent gap in an agent's timeline

Records carry `t`, seconds since the team's release barrier, so times line up
with the deadline the agents were shown. Reads no network and makes no model
calls.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path

from inspect_ai.log import read_eval_log


def content_parts(content):
    """Split message content into (reasoning, visible text)."""
    if content is None:
        return None, None
    if isinstance(content, str):
        return None, content or None
    reasoning, text = [], []
    for part in content:
        kind = getattr(part, "type", None)
        if kind == "reasoning":
            reasoning.append(getattr(part, "reasoning", "") or "")
        elif getattr(part, "text", None) is not None:
            text.append(part.text)
    return ("\n".join(p for p in reasoning if p) or None,
            "\n".join(p for p in text if p) or None)


def as_text(result):
    """Tool results are a string or a list of content parts."""
    if result is None or isinstance(result, str):
        return result
    if isinstance(result, list):
        _, text = content_parts(result)
        return text
    return str(result)


def owning_agent(span_id, spans):
    """Walk the span parents until the enclosing agent span is found.

    Tool and model events sit in nested spans, and ToolEvent.agent is not
    populated by this harness, so the parent chain is the reliable attribution.
    """
    seen = set()
    while span_id and span_id in spans and span_id not in seen:
        seen.add(span_id)
        span = spans[span_id]
        if span.type == "agent":
            return span.name
        span_id = span.parent_id
    return None


def resolve(target: Path):
    """Accept a run directory or a .eval path; return (log path, t0, run dir)."""
    if target.is_dir():
        manifest = json.loads((target / "manifest.json").read_text())
        log_path = Path(manifest["eval"])
        if not log_path.exists():
            # Logs recorded on another machine keep their original absolute path.
            local = Path.cwd() / log_path.name
            if not local.exists():
                raise SystemExit(f"Log not found: {log_path}\nAlso tried: {local}")
            log_path = local
        started = None
        for name, field in (("clock.json", "started_at"), ("team.json", "release_barrier_at")):
            path = target / name
            if started is None and path.exists():
                started = json.loads(path.read_text()).get(field)
        return log_path, started, target
    return target, None, target.parent


def extract(log_path: Path, started_at: str | None):
    log = read_eval_log(str(log_path), resolve_attachments=True)
    if not log.samples:
        raise SystemExit(f"No samples in {log_path}")
    sample = log.samples[0]
    spans = {e.id: e for e in sample.events if e.event == "span_begin"}

    models = [e for e in sample.events if e.event == "model"]
    tools = [e for e in sample.events if e.event == "tool"]

    # Each tool call inherits the reasoning and visible text of the response
    # that emitted it. One response may emit several calls.
    context, called = {}, set()
    for event in models:
        for choice in (event.output.choices if event.output else None) or []:
            reasoning, text = content_parts(choice.message.content)
            for call in choice.message.tool_calls or []:
                context[call.id] = (reasoning, text, event)
                called.add(id(event))

    t0 = datetime.fromisoformat(started_at) if started_at else min(
        e.timestamp for e in sample.events if getattr(e, "timestamp", None))

    def at(timestamp):
        return round((timestamp - t0).total_seconds(), 3)

    records = []
    for event in tools:
        reasoning, text, source = context.get(event.id, (None, None, None))
        records.append({
            "t": at(event.timestamp),
            "time": event.timestamp.isoformat(),
            "agent": owning_agent(event.span_id, spans),
            "type": "tool_call",
            "tool": event.function,
            "arguments": event.arguments,
            "output": as_text(event.result),
            "error": event.error.message if event.error else None,
            "reasoning": reasoning,
            "message": text,
            "duration_s": round(event.working_time, 3) if event.working_time is not None else None,
            "decided_at": at(source.timestamp) if source is not None else None,
        })

    for event in models:
        agent = owning_agent(event.span_id, spans)
        if event.error:
            records.append({
                "t": at(event.timestamp), "time": event.timestamp.isoformat(),
                "agent": agent, "type": "model_error", "tool": None, "arguments": None,
                "output": None, "error": str(event.error), "reasoning": None,
                "message": None, "duration_s": None, "decided_at": None,
            })
        elif id(event) not in called:
            # A response with no tool call still carries visible output worth keeping.
            reasoning = text = None
            for choice in (event.output.choices if event.output else None) or []:
                reasoning, text = content_parts(choice.message.content)
                break
            if reasoning or text:
                records.append({
                    "t": at(event.timestamp), "time": event.timestamp.isoformat(),
                    "agent": agent, "type": "message", "tool": None, "arguments": None,
                    "output": None, "error": None, "reasoning": reasoning,
                    "message": text, "duration_s": None, "decided_at": None,
                })

    records.sort(key=lambda r: (r["t"], r["agent"] or "", r["type"]))
    for index, record in enumerate(records, start=1):
        record["seq"] = index
    return records, log


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", type=Path, help="Run directory, or a path to a .eval log")
    parser.add_argument("--output", type=Path, help="Default: events.jsonl inside the run directory")
    args = parser.parse_args()

    log_path, started_at, run_dir = resolve(args.target)
    records, log = extract(log_path, started_at)
    output = args.output or run_dir / "events.jsonl"
    with output.open("w") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")

    agents, kinds = {}, {}
    for record in records:
        agents[record["agent"]] = agents.get(record["agent"], 0) + 1
        kinds[record["type"]] = kinds.get(record["type"], 0) + 1
    span = f"{records[0]['t']:.1f}s to {records[-1]['t']:.1f}s" if records else "empty"
    print(f"{output}: {len(records)} events, {span}"
          f"{'' if started_at else ' (t0 = first event; no clock.json)'}")
    print(f"  types  {kinds}")
    print(f"  agents {dict(sorted(agents.items(), key=lambda kv: -kv[1]))}")


if __name__ == "__main__":
    main()
