"""Stage 3: match detected events to ground-truth labels.

Answers three key questions:
- was the event detected (did a ground truth label find a matching event)
- was it matched correctly (was the detected event the closes available event of same type)
- how accurate was the timing (how many ms early or late was detection)
"""


import csv
from dataclasses import dataclass, field


DEFAULT_TOLERANCE_MS = {
    "LID_OPEN": 1500,
    "TILT": 1500,
    "SHOCK": 1000,
    "WALL1": 1000,
    "WALL2": 1000,
    "LIGHT_LEAK": 2000,
}


@dataclass(frozen=True)
class Label:
    type: str
    t_ms: int


@dataclass
class Match:
    label: Label
    event: object
    latency_ms: int


@dataclass
class MatchResult:
    matches: list
    false_negatives: list
    false_positives: list
    ignored: list = field(default_factory=list)


def load_labels(path):
    """Read and validate labels from a CSV file."""
    labels = []

    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for line, row in enumerate(reader, start=2):
            event_type = row["type"].strip().upper()

            if event_type not in DEFAULT_TOLERANCE_MS:
                raise ValueError(f"Line {line}: unknown type {event_type}")

            try:
                time = int(row["t_ms"])
            except ValueError:
                raise ValueError(f"Line {line}: t_ms must be an integer")

            labels.append(Label(event_type, time))

    return sorted(labels, key=lambda label: label.t_ms)


def match_events(events, labels, tolerance=None, skip_start_artifacts=True):
    """Match detected events with reference labels."""

    # Set matching tolerances
    tol = DEFAULT_TOLERANCE_MS.copy()
    if tolerance:
        tol.update(tolerance)

    # Remove events caused by initial setup
    ignored = []

    if skip_start_artifacts:
        ignored = [e for e in events if e.started_at_start]
        events = [e for e in events if not e.started_at_start]

    # Find all possible matches
    pairs = []

    for i, label in enumerate(labels):
        for j, event in enumerate(events):

            if event.type != label.type:
                continue

            difference = abs(event.start_ms - label.t_ms)

            if difference <= tol[label.type]:
                pairs.append((difference, i, j))

    # Prefer matches with the smallest time difference
    pairs.sort()

    used_labels = set()
    used_events = set()
    matches = []

    for difference, i, j in pairs:

        if i in used_labels or j in used_events:
            continue

        used_labels.add(i)
        used_events.add(j)

        latency = events[j].start_ms - labels[i].t_ms

        matches.append(
            Match(labels[i], events[j], latency)
        )

    # Identify unmatched labels and events
    false_negatives = [
        label for i, label in enumerate(labels)
        if i not in used_labels
    ]

    false_positives = [
        event for j, event in enumerate(events)
        if j not in used_events
    ]

    matches.sort(key=lambda match: match.label.t_ms)

    return MatchResult(
        matches=matches,
        false_negatives=false_negatives,
        false_positives=false_positives,
        ignored=ignored
    )
