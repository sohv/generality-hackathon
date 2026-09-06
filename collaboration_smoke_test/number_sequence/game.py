"""Authoritative append-only sequence and independent scoring."""
import bisect
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


def ordered_pairs(sequence: list[int], numbers: list[int]) -> tuple[int, int]:
    """Count number pairs submitted in the correct relative order, out of all pairs.

    A pair scores only when both numbers were submitted and the smaller one was
    submitted first, so never submitting forfeits every pair that number belongs
    to. Unlike exact positions, one displaced number costs only the pairs it
    actually inverts, and the chance level is 50% at every team size.
    """
    position = {value: index for index, value in enumerate(sequence)}
    target = sorted(numbers)
    total = len(target) * (len(target) - 1) // 2
    correct = sum(smaller in position and larger in position
                  and position[smaller] < position[larger]
                  for index, smaller in enumerate(target) for larger in target[index + 1:])
    return correct, total


def diagnostics(sequence: list[int], numbers: list[int]) -> dict:
    """Every metric the run records, whichever one is the reward."""
    target = sorted(numbers)
    exact = [i + 1 for i, (actual, expected) in enumerate(zip(sequence, target)) if actual == expected]
    pairs, total_pairs = ordered_pairs(sequence, numbers)
    ideal = {value: index for index, value in enumerate(target)}
    worst = len(target) ** 2 // 2
    missing = [value for value in target if value not in set(sequence)]
    offset = (sum(abs(index - ideal[value]) for index, value in enumerate(sequence) if value in ideal)
              + (len(target) - 1) * len(missing))
    run = []
    for value in sequence:
        index = bisect.bisect_left(run, value)
        run.append(value) if index == len(run) else run.__setitem__(index, value)
    return {"exact_positions_percent": 100 * len(exact) / len(target),
            "ordered_pairs_percent": 100 * pairs / total_pairs if total_pairs else 100.0,
            "ordered_pairs": pairs, "total_pairs": total_pairs,
            "displacement_percent": 100 * max(0.0, 1 - offset / worst) if worst else 100.0,
            "longest_increasing_run_percent": 100 * len(run) / len(target),
            "submitted_percent": 100 * len(sequence) / len(target),
            "correct_positions": exact, "missing_numbers": missing}


def positional_score(sequence: list[int], numbers: list[int], rule: str = "exact_positions") -> dict:
    """Score one finished sequence. `rule` selects which metric is the reward."""
    target = sorted(numbers)
    metrics = diagnostics(sequence, numbers)
    if rule == "ordered_pairs":
        percent, correct, expected = (metrics["ordered_pairs_percent"], metrics["ordered_pairs"],
                                      metrics["total_pairs"])
        described = "correctly_ordered_number_pairs_percent"
    elif rule == "exact_positions":
        percent, correct, expected = (metrics["exact_positions_percent"],
                                      len(metrics["correct_positions"]), len(target))
        described = "correct_positions_in_full_sorted_roster_percent"
    else:
        raise ValueError(f"Unknown scoring rule: {rule}")
    return {"sequence": sequence, "expected_sequence": target,
            "correct_positions": metrics["correct_positions"],
            "correct_count": correct, "expected_count": expected,
            "score_percent": percent,
            "all_correct": sequence == target,
            "scoring_rule": described, "reward_rule": rule, "metrics": metrics}


class SequenceGame:
    def __init__(self, directory: Path, assignments: dict[str, int], continue_after_submit: bool = False):
        if len(set(assignments.values())) != len(assignments) or not assignments:
            raise ValueError("Assignments must be nonempty and unique")
        if any(type(n) is not int or not 1 <= n <= 2000 for n in assignments.values()):
            raise ValueError("Assigned numbers must be integers from 1 to 2000")
        self.directory = directory
        self.assignments = assignments
        self.entries: list[dict] = []
        self.submitted: set[str] = set()
        # Task version 8: submitting records a number but does not end the rollout.
        # Participation then ends only via the exit tool, a limit, or the deadline.
        self.continue_after_submit = continue_after_submit
        self.exited: set[str] = set()
        self.exits: list[dict] = []
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

    def remaining(self):
        return max(0.0, self.deadline_seconds - self.elapsed())

    def grant_wait(self, owner: str, seconds: float) -> float:
        """Version 11: how long an agent may actually pause.

        A pause can never outlast the team deadline, so an agent that asks for
        more than the time left is held until the deadline and no longer. The
        request and the grant are both recorded, because the difference is the
        agent misjudging the clock.
        """
        with self.lock:
            self.check_active(owner)
            granted = seconds if self.started is None else min(seconds, self.remaining())
            granted = max(0.0, granted)
            self.audit_decision(owner, "wait", requested_seconds=seconds, granted_seconds=granted,
                                elapsed_seconds=self.elapsed())
            return granted

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
                   + ("You keep your file tools after submitting: tell your peers that you have submitted, then call "
                      "exit_rollout when you have nothing left to contribute. "
                      if self.continue_after_submit else "")
                   + "Call exactly one tool next; additional calls in the same response will be rejected.")
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
        if owner in self.submitted and not self.continue_after_submit:
            raise ToolError("You already submitted; your participation has ended")
        if owner in self.exited:
            raise ToolError("You ended your own participation")
        if not self.active:
            raise ToolError("The team attempt has ended")
        if self.enforce_deadline and self.started is not None and self.elapsed() >= self.deadline_seconds:
            raise ToolError(f"The {self.deadline_seconds / 60:g}-minute team deadline has expired; no further actions or submissions are accepted")

    def submit(self, owner: str) -> dict:
        with self.lock:
            self.check_active(owner)
            if owner in self.submitted:
                raise ToolError("You already submitted your number; a number can be submitted only once")
            entry = {"position": len(self.entries) + 1, "number": self.assignments[owner],
                     "agent": owner, "submitted_at": now(), "elapsed_seconds": self.elapsed()}
            # Arrival order is preserved. No sorting, turn scheduling, or rejection
            # of an out-of-order number is performed by the harness.
            self.entries.append(entry)
            self.submitted.add(owner)
            self.persist()
            with (self.directory / "submission_audit.jsonl").open("a") as audit:
                audit.write(json.dumps(entry) + "\n")
            return {"submitted": entry["number"],
                    "participation_ended": not self.continue_after_submit}

    def end_participation(self, owner: str) -> dict:
        """Version 8 only: the agent's own irreversible exit from its rollout."""
        with self.lock:
            self.check_active(owner)
            record = {"agent": owner, "submitted": owner in self.submitted,
                      "exited_at": now(), "elapsed_seconds": self.elapsed()}
            self.exited.add(owner)
            self.exits.append(record)
            save(self.directory / "exits.json", self.exits)
            self.audit_decision(owner, "exit", submitted=record["submitted"],
                                elapsed_seconds=record["elapsed_seconds"])
            return {"participation_ended": True, "submitted_before_exiting": record["submitted"]}

    def persist(self):
        save(self.directory / "sequence.json", [e["number"] for e in self.entries])
        save(self.directory / "submissions.json", self.entries)

    def freeze(self) -> list[int]:
        with self.lock:
            self.active = False
            self.persist()
            return [e["number"] for e in self.entries]
