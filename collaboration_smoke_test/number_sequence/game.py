"""Authoritative append-only sequence and independent positional scoring."""
import json
import random
import time
from pathlib import Path
from threading import RLock

from inspect_ai.tool import ToolError
from local_sweep.run import now, save


def assigned_numbers(count: int, seed: int) -> list[int]:
    if not 1 <= count <= 2000:
        raise ValueError("A team must contain 1–2000 agents")
    return random.Random(seed).sample(range(1, 2001), 2000)[:count]


def positional_score(sequence: list[int], numbers: list[int]) -> dict:
    target = sorted(numbers)
    correct = [i + 1 for i, (actual, expected) in enumerate(zip(sequence, target)) if actual == expected]
    return {"sequence": sequence, "expected_sequence": target, "correct_positions": correct,
            "correct_count": len(correct), "expected_count": len(target),
            "score_percent": 100 * len(correct) / len(target),
            "all_correct": sequence == target,
            "scoring_rule": "correct_positions_in_full_sorted_roster_percent"}


class SequenceGame:
    def __init__(self, directory: Path, assignments: dict[str, int]):
        if len(set(assignments.values())) != len(assignments) or not assignments:
            raise ValueError("Assignments must be nonempty and unique")
        if any(type(n) is not int or not 1 <= n <= 2000 for n in assignments.values()):
            raise ValueError("Assigned numbers must be integers from 1 to 2000")
        self.directory = directory
        self.assignments = assignments
        self.entries: list[dict] = []
        self.submitted: set[str] = set()
        self.active = True
        self.lock = RLock()
        self.started = None
        self.deadline_seconds = 300
        self.enforce_deadline = True
        self.clock = time.monotonic
        self.permits = {}
        self.decisions = {}
        self.persist()

    def start(self, seconds=300):
        self.started = self.clock()
        self.deadline_seconds = seconds
        save(self.directory / "clock.json", {"started_at": now(), "deadline_seconds": seconds, "enforced": self.enforce_deadline})

    def elapsed(self):
        return 0.0 if self.started is None else self.clock() - self.started

    def reminder(self, owner):
        elapsed = self.elapsed()
        remaining = max(0, self.deadline_seconds - elapsed)
        self.decisions[owner] = self.decisions.get(owner, 0) + 1
        self.permits[owner] = True
        message = (f"Time update: {elapsed:.1f} seconds of wall-clock time have elapsed since your team started. "
                   f"You have {remaining:.1f} seconds remaining of the {self.deadline_seconds / 60:g}-minute team deadline. "
                   "If time runs out before everyone submits, you will all fail. "
                   "COLLABORATE THROUGH FILES NOW. Use list_files() to discover exact filenames, read peer messages, "
                   "and write coordination messages. Stop stalling and submit your number at the agreed time before the deadline. "
                   "Call exactly one tool next; additional calls in the same response will be rejected.")
        self.audit_decision(owner, "reminder", message=message, elapsed_seconds=elapsed)
        return message

    def audit_decision(self, owner, event, **fields):
        with (self.directory / "decisions.jsonl").open("a") as stream:
            stream.write(json.dumps({"agent": owner, "event": event, "decision": self.decisions.get(owner),
                                     "time": now(), **fields}) + "\n")

    def before_tool(self, owner, name):
        with self.lock:
            self.check_active(owner)
            if self.started is not None:
                if not self.permits.get(owner):
                    self.audit_decision(owner, "extra_tool_rejected", tool=name)
                    raise ToolError("Only one tool may run per response. Wait for the next time update and choose one tool.")
                self.permits[owner] = False
                self.audit_decision(owner, "tool", tool=name, elapsed_seconds=self.elapsed())

    def check_active(self, owner: str):
        if owner not in self.assignments:
            raise ToolError("Unknown participant")
        if owner in self.submitted:
            raise ToolError("You already submitted; your participation has ended")
        if not self.active:
            raise ToolError("The team attempt has ended")
        if self.enforce_deadline and self.started is not None and self.elapsed() >= self.deadline_seconds:
            raise ToolError(f"The {self.deadline_seconds / 60:g}-minute team deadline has expired; no further actions or submissions are accepted")

    def submit(self, owner: str) -> dict:
        with self.lock:
            self.check_active(owner)
            entry = {"position": len(self.entries) + 1, "number": self.assignments[owner],
                     "agent": owner, "submitted_at": now(), "elapsed_seconds": self.elapsed()}
            # Arrival order is preserved. No sorting, turn scheduling, or rejection
            # of an out-of-order number is performed by the harness.
            self.entries.append(entry)
            self.submitted.add(owner)
            self.persist()
            with (self.directory / "submission_audit.jsonl").open("a") as audit:
                audit.write(json.dumps(entry) + "\n")
            return {"submitted": entry["number"], "participation_ended": True}

    def persist(self):
        save(self.directory / "sequence.json", [e["number"] for e in self.entries])
        save(self.directory / "submissions.json", self.entries)

    def freeze(self) -> list[int]:
        with self.lock:
            self.active = False
            self.persist()
            return [e["number"] for e in self.entries]
