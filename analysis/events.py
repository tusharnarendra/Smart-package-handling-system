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
import pandas as pd


INTERVAL_STATES = {
    "LID_OPEN": "lid_open",
    "TILT": "tilt_abnormal",
    "WALL1": "wall1_pressed",
    "WALL2": "wall2_pressed",
}

REQUIRED_COLUMNS = ("elapsed", "event", "lid_open", "tilt_abnormal","wall1_pressed", "wall2_pressed")

def check_columns(rows):
    """Reject logs missing columns the analysis needs (e.g. old 7-column CSVs)."""
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    if missing:
        raise ValueError(
            "wrong CSV format, missing columns: "
            + ", ".join(missing)
        )

@dataclass(frozen=True)
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
        data = asdict(self)
        data["duration_ms"] = self.duration_ms
        return data


def extract_events(rows):
    """Extract events from sensor data."""

    if not rows:
        return []

    events = []
    last_time = rows[-1]["elapsed"]

    # Extract interval events
    for event_type, column in INTERVAL_STATES.items():

        start_time = None
        started_at_start = False

        for i, row in enumerate(rows):
            active = bool(row[column])

            # Event starts
            if active and start_time is None:
                start_time = row["elapsed"]
                started_at_start = (i == 0)

            # Event ends
            elif not active and start_time is not None:
                events.append(Event(
                    event_type,
                    start_time,
                    row["elapsed"],
                    False,
                    started_at_start
                ))

                start_time = None

        # Event is still active at the end
        if start_time is not None:
            events.append(Event(
                event_type,
                start_time,
                last_time,
                True,
                started_at_start
            ))

    # Extract shock events
    for row in rows:
        if row["event"] == "SHOCK_EVENT":
            time = row["elapsed"]
            events.append(Event("SHOCK", time, time))

    # Sort events by start time
    return sorted(events, key=lambda e: (e.start_ms, e.type))


def find_arrival(rows):
    """Find the time when arrival was first recorded."""

    for row in rows:
        if row["event"] == "ARRIVED":
            return row["elapsed"]

    return None


def events_dataframe(events):
    """Convert events into a pandas DataFrame."""

    columns = [
        "type",
        "start_ms",
        "end_ms",
        "duration_ms",
        "open_ended",
        "started_at_start",
    ]

    return pd.DataFrame(
        [event.as_dict() for event in events],
        columns=columns
    )
