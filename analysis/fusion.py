"""Stage 2: events + light -> explainable suspicion levels.

Lid + Light rules:

Closed + dark -> NORMAL (0 points)
Open + dark -> LID_OPEN_DARK (4 points)
Open + bright -> LID_OPEN_BRIGHT (4 points)
Closed + bright -> LIGHT_LEAK (1 point)
Other sensor events are scored independently:

SHOCK -> 1 point
TILT -> 1 point
WALL1 -> 1 point
WALL2 -> 1 point
Suspicion levels (based on total points):

0 points -> Normal
1-2 points -> Handling event
3-5 points -> Suspicious
6+ points -> High suspicion

"""

from dataclasses import dataclass, field, replace
from analysis.events import Event, find_arrival


LEVELS = ["normal", "handling event", "suspicious", "high suspicion"]


@dataclass
class FusionConfig:
    bright_delta: int | None = None
    leak_min_ms: int = 500
    window_ms: int | None = None
    level_min_points: tuple = (1, 3, 6)

    points: dict = field(default_factory=lambda: {
        "LID_OPEN_DARK": 4,
        "LID_OPEN_BRIGHT": 4,
        "LID_OPEN_UNKNOWN": 4,
        "LIGHT_LEAK": 1,
        "SHOCK": 1,
        "TILT": 1,
        "WALL1": 1,
        "WALL2": 1,
    })
    
    # Merge same-type events if they happen close together (ms).
    merge_gap_ms: dict = field(default_factory=lambda: {
        "LID_OPEN": 1000,
        "TILT": 3000,
        "WALL1": 2000,
        "WALL2": 2000,
        "SHOCK": 500,
        "LIGHT_LEAK": 1000,
    })

    # Add 1 point for each full time step (ms).
    duration_step_ms: dict = field(default_factory=lambda: {
        "TILT": 30000,
        "WALL1": 10000,
        "WALL2": 10000,
        "LIGHT_LEAK": 10000,
    })

    # Maximum points allowed for each event type to stop noisy sensors from out
    max_points_per_type: dict = field(default_factory=lambda: {
        "SHOCK": 4,
        "TILT": 3,
        "WALL1": 3,
        "WALL2": 3,
        "LIGHT_LEAK": 2,
    })

@dataclass
class Scored:
    event: Event
    key: str
    points: int
    merged: int = 1 # how many events were merged into this episode


@dataclass
class Assessment:
    scored: list
    score: int
    current_level: str
    worst_level: str
    flags: list
    arrival_ms: int | None = None
    transit_ms: int = 0 # start to end of run
    points_per_hour: float = 0.0

def merge_close(events, gaps):
    """Merge nearby events of the same type."""

    by_type = {}

    for event in sorted(events, key=lambda e: e.start_ms):
        by_type.setdefault(event.type, []).append(event)

    merged = []

    for event_type, group in by_type.items():
        gap = gaps.get(event_type, 0)
        current = group[0]
        count = 1

        for event in group[1:]:

            # Merge if the gap is small enough
            if event.start_ms - current.end_ms <= gap:
                current = replace(
                    current,
                    end_ms=max(current.end_ms, event.end_ms),
                    open_ended=current.open_ended or event.open_ended
                )
                count += 1

            else:
                merged.append((current, count))
                current = event
                count = 1

        merged.append((current, count))

    return merged


def event_points(key, event, cfg):
    """Calculate event points, including duration bonus."""

    base = cfg.points.get(key, 0)

    if base == 0:
        return 0

    step = cfg.duration_step_ms.get(event.type)
    bonus = event.duration_ms // step if step else 0

    return base + bonus


def level_for(score, cfg):
    """Determine the risk level from the total score."""
    level = sum(score >= points for points in cfg.level_min_points)
    return LEVELS[level]


def is_bright(row, cfg):
    """Check whether the light level is considered bright."""
    threshold = cfg.bright_delta

    if threshold is None:
        return False

    if threshold < 0:
        return row["light_delta"] <= threshold

    return row["light_delta"] >= threshold


def lid_light_state(event, rows, cfg):
    """Determine whether the lid opening happened in bright or dark conditions."""
    if cfg.bright_delta is None:
        return "unknown"

    for row in rows:
        if event.start_ms <= row["elapsed"] <= event.end_ms:
            if is_bright(row, cfg):
                return "bright"

    return "dark"


def leak_events(rows, cfg):
    """Find periods when the lid is closed but bright light is detected."""
    if cfg.bright_delta is None:
        return []

    leaks = []
    start_time = None

    for row in rows:
        leaking = not row["lid_open"] and is_bright(row, cfg)

        if leaking and start_time is None:
            start_time = row["elapsed"]

        elif not leaking and start_time is not None:
            if row["elapsed"] - start_time >= cfg.leak_min_ms:
                leaks.append(
                    Event("LIGHT_LEAK", start_time, row["elapsed"])
                )

            start_time = None

    # Check whether a leak continues until the end
    if start_time is not None:
        end_time = rows[-1]["elapsed"]

        if end_time - start_time >= cfg.leak_min_ms:
            leaks.append(
                Event("LIGHT_LEAK", start_time, end_time, open_ended=True)
            )

    return leaks


def assess(rows, events, cfg=None, arrival_ms=None):
    """Calculate event scores and determine the final risk level."""

    if not rows:
        raise ValueError("rows cannot be empty")

    if cfg is None:
        cfg = FusionConfig()

    if arrival_ms is None:
        arrival_ms = find_arrival(rows)

    scored = []
    flags = []

    # Combine detected events and light leak events, then merge repeats
    all_events = list(events) + leak_events(rows, cfg)
    episodes = merge_close(all_events, cfg.merge_gap_ms)

    for event, count in episodes:
        
        # Ignore events occurring after arrival
        if arrival_ms is not None and event.start_ms >= arrival_ms:
            scored.append(Scored(event, "AFTER_ARRIVAL", 0))
            continue

        # Determine the event category
        if event.type == "LID_OPEN":

            if event.started_at_start:
                flags.append(
                    "Lid open at START: setup problem, opening not scored"
                )
                scored.append(Scored(event, "LID_OPEN_AT_START", 0))
                continue

            light_state = lid_light_state(event, rows, cfg)
            key = "LID_OPEN_" + light_state.upper()

        else:
            key = event.type

        # Assign points
        points = event_points(key, event, cfg)
        scored.append(Scored(event, key, points, count))

    # Add warnings
    if cfg.bright_delta is None:
        flags.append(
            "Light not calibrated: openings scored as LID_OPEN_UNKNOWN"
        )

    if arrival_ms is not None:
        flags.append(
            f"Events from {arrival_ms} ms onward treated as after arrival, not scored"
        )

    # Calculate score at a given time
    def score_at(time):
        per_type = {}

        for item in scored:
            event_time = item.event.start_ms

            if event_time > time:
                continue

            if cfg.window_ms is not None:
                if event_time <= time - cfg.window_ms:
                    continue

            event_type = item.event.type
            per_type[event_type] = per_type.get(event_type, 0) + item.points

        # Apply the per-type cap
        return sum(
            min(points, cfg.max_points_per_type.get(event_type, points))
            for event_type, points in per_type.items()
        )

    # Calculate the highest score during the recording
    times = sorted({
        item.event.start_ms
        for item in scored
        if item.points > 0
    })

    worst_score = max(
        (score_at(time) for time in times),
        default=0
    )

    # Calculate the final score
    final_score = score_at(rows[-1]["elapsed"])

    end_ms = arrival_ms if arrival_ms is not None else rows[-1]["elapsed"]
    transit_ms = max(end_ms - rows[0]["elapsed"], 1)
    points_per_hour = final_score / (transit_ms / 3_600_000)
    
    # Create the final assessment
    return Assessment(
        scored=sorted(scored, key=lambda item: item.event.start_ms),
        score=final_score,
        current_level=level_for(final_score, cfg),
        worst_level=level_for(worst_score, cfg),
        flags=flags,
        arrival_ms=arrival_ms,
        transit_ms = transit_ms,
        points_per_hour=points_per_hour
    )
