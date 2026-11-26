from dataclasses import dataclass, field
from analysis.events import REQUIRED_COLUMNS, extract_events

MIN_RUN_MS = 10_000
MAX_GAP_MS = 3_000

# Counter names and their corresponding event types
COUNTERS = {
    "shock_count": "SHOCK",
    "tilt_count": "TILT",
    "wall1_count": "WALL1",
    "wall2_count": "WALL2",
}


@dataclass
class Validity:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


def validate_run(rows, min_run_ms=MIN_RUN_MS, max_gap_ms=MAX_GAP_MS):
    """Check whether a run has enough valid data for analysis."""

    result = Validity()

    # Check if data exists
    if not rows:
        result.errors.append("No rows")
        return result

    # Check required columns
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]

    if missing:
        result.errors.append("Missing columns: " + ", ".join(missing))
        return result

    events = [row["event"] for row in rows]
    duration = rows[-1]["elapsed"] - rows[0]["elapsed"]

    # Check START and END markers
    if "START" not in events:
        result.errors.append("No START row")

    if "END" not in events:
        result.warnings.append("No END row: run may have been cut short")

    # Check recording duration
    if duration < min_run_ms:
        result.errors.append(
            f"Run too short ({duration} ms < {min_run_ms} ms)"
        )

    # Check for missing data
    for a, b in zip(rows, rows[1:]):
        gap = b["elapsed"] - a["elapsed"]

        if gap > max_gap_ms:
            result.warnings.append(
                f"Gap of {gap} ms at {a['elapsed']} ms: possible missing data"
            )

    # Check that counters never decrease
    for column in COUNTERS:
        if column not in rows[0]:
            continue

        for a, b in zip(rows, rows[1:]):
            if b[column] < a[column]:
                result.errors.append(
                    f"{column} decreased at {b['elapsed']} ms: log is corrupted"
                )
                break

    # Check if the lid was already open at the start
    if rows[0]["lid_open"]:
        result.warnings.append(
            "Lid open at start: opening will not be scored"
        )

    # Count extracted events
    extracted = {}

    for event in extract_events(rows):
        extracted[event.type] = extracted.get(event.type, 0) + 1

    # Compare event counts with sensor counters
    for column, event_type in COUNTERS.items():

        if column not in rows[0]:
            continue

        counted = rows[-1][column] - rows[0][column]
        found = extracted.get(event_type, 0)

        if counted != found:
            result.warnings.append(
                f"{event_type}: counter says {counted}, events found {found}"
            )

    return result
