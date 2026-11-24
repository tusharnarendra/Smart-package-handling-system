"""Stage 3: match detected events to ground-truth labels.

Answers three key questions:
- was the event detected (did a ground truth label find a matching event)
- was it matched correctly (was the detected event the closes available event of same type)
- how accurate was the timing (how many ms early or late was detection)
"""

import csv
from dataclasses import dataclass, field


DEFAULT_TOLERANCE_MS = {
    "LID_OPEN": 1500, "TILT": 1500, "SHOCK": 1000,
    "WALL1": 1000, "WALL2": 1000, "LIGHT_LEAK": 2000,
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
    matches: list                 # true positives
    false_negatives: list         # labels with no event
    false_positives: list         # events with no label
    ignored: list = field(default_factory=list)  # events skipped (setup artifacts)


def load_labels(path):
    labels = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for n, row in enumerate(csv.DictReader(f), 2):
            t = row["type"].strip().upper()
            if t not in DEFAULT_TOLERANCE_MS:
                raise ValueError(f"{path} line {n}: unknown label type {t!r}")
            try:
                labels.append(Label(t, int(row["t_ms"])))
            except ValueError:
                raise ValueError(f"{path} line {n}: t_ms must be an integer")
    return sorted(labels, key=lambda l: l.t_ms)


def match_events(events, labels, tolerance=None, skip_start_artifacts=True):
    tol = {**DEFAULT_TOLERANCE_MS, **(tolerance or {})}
    ignored = []
    if skip_start_artifacts:
        # e.g. lid already open in the START row: a setup problem, not a detection
        ignored = [e for e in events if e.started_at_start]
        events = [e for e in events if not e.started_at_start]

    pairs = []
    for i, lab in enumerate(labels):
        for j, ev in enumerate(events):
            if ev.type == lab.type:
                d = abs(ev.start_ms - lab.t_ms)
                if d <= tol[lab.type]:
                    pairs.append((d, i, j))
    pairs.sort()

    used_l, used_e, matches = set(), set(), []
    for d, i, j in pairs:
        if i in used_l or j in used_e:
            continue
        used_l.add(i)
        used_e.add(j)
        matches.append(Match(labels[i], events[j], events[j].start_ms - labels[i].t_ms))

    return MatchResult(
        sorted(matches, key=lambda m: m.label.t_ms),
        [l for i, l in enumerate(labels) if i not in used_l],
        [e for j, e in enumerate(events) if j not in used_e],
        ignored,
    )
