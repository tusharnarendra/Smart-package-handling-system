"""
Convert raw sensor logs into events:
- input = valid csv rows with elapsed time
- track sensor changes across all rows
- record start time end time and duration of each event


Event types:
- LID_OPEN: Lid is open (either reed switch).
- TILT: Abnormal tilt detected.
- WALL1/2: Microswitch pressed.
- SHOCK: Shock detected (instant event, duration = 0).
"""

from dataclasses import dataclass, asdict

INTERVAL_STATES = {
    "LID_OPEN": lambda r: r["lid_open"],
    "TILT": lambda r: r["tilt_abnormal"],
    "WALL1": lambda r: r["wall1_pressed"],
    "WALL2": lambda r: r["wall2_pressed"],
}

@dataclass(frozen=True) # immutable object
class Event:
    type: str
    start_ms: int
    end_ms: int
    open_ended: bool = False 
    started_at_start: bool = False

    @property
    def duration_ms(self):
        return self.end_ms - self.start_ms

    def as_dict(self):
        d = asdict(self)
        d["duration_ms"] = self.duration_ms
        return d


def extract_events(rows):
    """rows: parsed dicts sorted by 'elapsed'. Returns Events sorted by start."""
    if not rows:
        return []
    events = []
    last_ms = rows[-1]["elapsed"]

    for etype, getter in INTERVAL_STATES.items():
        active_since, from_start = None, False
        for i, r in enumerate(rows):
            on = bool(getter(r))
            if on and active_since is None:
                active_since, from_start = r["elapsed"], (i == 0)
            elif not on and active_since is not None:
                events.append(Event(etype, active_since, r["elapsed"], False, from_start))
                active_since = None
        if active_since is not None:
            events.append(Event(etype, active_since, last_ms, True, from_start))

    for r in rows:
        if r["event"] == "SHOCK_EVENT":
            events.append(Event("SHOCK", r["elapsed"], r["elapsed"]))

    return sorted(events, key=lambda e: (e.start_ms, e.type))


def find_arrival(rows):
    """Elapsed ms of the first ARRIVED row, or None if arrival was never marked."""
    for r in rows:
        if r["event"] == "ARRIVED":
            return r["elapsed"]
    return None


def events_dataframe(events):
    import pandas as pd
    cols = ["type", "start_ms", "end_ms", "duration_ms", "open_ended", "started_at_start"]
    return pd.DataFrame([e.as_dict() for e in events], columns=cols)