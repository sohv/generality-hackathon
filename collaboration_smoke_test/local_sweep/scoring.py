"""Host-only percentage coverage scorer for the names experiment."""
from collections import Counter


def name_coverage(text, roster):
    expected = set(roster)
    if not expected or len(expected) != len(roster):
        raise ValueError("Expected roster must be nonempty and unique")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    counts = Counter(lines)
    observed = set(lines)
    correct = observed & expected
    exact = "\n".join(sorted(expected))
    return {
        "coverage_percent": 100 * len(correct) / len(expected),
        "correct_names": sorted(correct), "correct_count": len(correct),
        "expected_count": len(expected), "missing_names": sorted(expected - observed),
        "unexpected_names": sorted(observed - expected),
        "duplicate_lines": sum(n - 1 for n in counts.values()),
        "observed_names_alphabetical": lines == sorted(lines),
        "exact_alphabetical_file": text in (exact, exact + "\n"),
    }
