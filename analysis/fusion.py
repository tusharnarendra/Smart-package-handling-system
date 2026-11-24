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
from dataclasses import dataclass, field
from analysis.events import Event, find_arrival

LEVELS = ["normal", "handling event", "suspicious", "high suspicion"]


@dataclass
class FusionConfig:
    bright_delta: int | None = None   # e.g. -150 once calibrated
    leak_min_ms: int = 500            # bright-while-closed must last this long
    window_ms: int | None = None      # None = points never decay
    level_min_points: tuple = (1, 3, 6)  # lower bound for levels 1, 2, 3
    points: dict = field(default_factory=lambda: {
        "LID_OPEN_DARK": 4, "LID_OPEN_BRIGHT": 4, "LID_OPEN_UNKNOWN": 4,
        "LIGHT_LEAK": 1, "SHOCK": 1, "TILT": 1, "WALL1": 1, "WALL2": 1,
    })


@dataclass
class Scored:
    event: Event
    key: str
    points: int


@dataclass
class Assessment:
    scored: list
    score: int          # total points at end of run (after any decay)
    current_level: str
    worst_level: str
    flags: list
    arrival_ms: int | None = None


def level_for(score, cfg):
    return LEVELS[sum(score >= m for m in cfg.level_min_points)]


def is_bright(row, cfg):
    t = cfg.bright_delta
    if t is None:
        return False
    return row["light_delta"] <= t if t < 0 else row["light_delta"] >= t


def lid_light_state(event, rows, cfg):
    """'bright' if any row during the opening was bright, else 'dark'."""
    if cfg.bright_delta is None:
        return "unknown"
    during = [r for r in rows if event.start_ms <= r["elapsed"] <= event.end_ms]
    return "bright" if any(is_bright(r, cfg) for r in during) else "dark"


def leak_events(rows, cfg):
    """Closed lid + bright for at least leak_min_ms."""
    if cfg.bright_delta is None:
        return []
    out, since = [], None
    for r in rows:
        leaking = (not r["lid_open"]) and is_bright(r, cfg)
        if leaking and since is None:
            since = r["elapsed"]
        elif not leaking and since is not None:
            if r["elapsed"] - since >= cfg.leak_min_ms:
                out.append(Event("LIGHT_LEAK", since, r["elapsed"]))
            since = None
    if since is not None and rows[-1]["elapsed"] - since >= cfg.leak_min_ms:
        out.append(Event("LIGHT_LEAK", since, rows[-1]["elapsed"], open_ended=True))
    return out


def assess(rows, events, cfg=None, arrival_ms=None):
    cfg = cfg or FusionConfig()
    if arrival_ms is None:
        arrival_ms = find_arrival(rows)
    flags, scored = [], []
    for e in list(events) + leak_events(rows, cfg):
        if arrival_ms is not None and e.start_ms >= arrival_ms:
            scored.append(Scored(e, "AFTER_ARRIVAL", 0))
            continue
        if e.type == "LID_OPEN":
            if e.started_at_start:
                flags.append("Lid open at START: setup problem, opening not scored")
                scored.append(Scored(e, "LID_OPEN_AT_START", 0))
                continue
            key = "LID_OPEN_" + lid_light_state(e, rows, cfg).upper()
        else:
            key = e.type
        scored.append(Scored(e, key, cfg.points.get(key, 0)))
    if cfg.bright_delta is None:
        flags.append("Light not calibrated: openings scored as LID_OPEN_UNKNOWN")
    if arrival_ms is not None:
        flags.append(f"Events from {arrival_ms} ms onward treated as after arrival, not scored")

    def score_at(t):
        return sum(s.points for s in scored
                   if s.event.start_ms <= t
                   and (cfg.window_ms is None or s.event.start_ms > t - cfg.window_ms))

    times = sorted({s.event.start_ms for s in scored if s.points})
    worst = max([score_at(t) for t in times], default=0)
    final = score_at(rows[-1]["elapsed"])
    return Assessment(sorted(scored, key=lambda s: s.event.start_ms), final,
                      level_for(final, cfg), level_for(worst, cfg), flags,
                      arrival_ms)
