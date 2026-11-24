"""Stage 4: detection metrics per event type, from MatchResults.

Uses MatchResults from Stage 3 to evaluate how accurately the system detects events.

Calculates true positives (TP), false positives (FP), false negatives (FN), precision, recall, and their 95% Wilson confidence intervals. Also measures false alarms per minute and detection latency (median and IQR, in milliseconds).

Undefined metrics are reported as None, not 0. For example, recall is undefined when no ground-truth labels exist for an event type.

For negative-control trials (where no events should occur), false alarms per minute is particularly important.

Multiple trials can be pooled by providing their MatchResults and recording durations in milliseconds, in the same order. 
"""
import math
from dataclasses import dataclass


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n. None if n == 0."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def percentile(sorted_values, q):
    """Linear-interpolation percentile, q in [0, 1]. None for an empty list."""
    if not sorted_values:
        return None
    pos = q * (len(sorted_values) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


@dataclass
class TypeMetrics:
    type: str
    tp: int
    fp: int
    fn: int
    precision: float | None
    precision_ci: tuple | None
    recall: float | None
    recall_ci: tuple | None
    false_alarms_per_min: float | None
    latency_median_ms: float | None
    latency_q1_ms: float | None
    latency_q3_ms: float | None


def _metrics(name, tp, fp, fn, latencies, minutes):
    lat = sorted(latencies)
    return TypeMetrics(
        name, tp, fp, fn,
        tp / (tp + fp) if tp + fp else None, wilson(tp, tp + fp),
        tp / (tp + fn) if tp + fn else None, wilson(tp, tp + fn),
        fp / minutes if minutes else None,
        percentile(lat, 0.5), percentile(lat, 0.25), percentile(lat, 0.75),
    )


def compute_metrics(results, durations_ms):
    """Returns {event type: TypeMetrics, ..., 'ALL': TypeMetrics}."""
    if len(results) != len(durations_ms):
        raise ValueError("results and durations_ms must have the same length")
    minutes = sum(durations_ms) / 60000
    lat, tp, fp, fn = {}, {}, {}, {}
    for r in results:
        for m in r.matches:
            t = m.label.type
            tp[t] = tp.get(t, 0) + 1
            lat.setdefault(t, []).append(m.latency_ms)
        for l in r.false_negatives:
            fn[l.type] = fn.get(l.type, 0) + 1
        for e in r.false_positives:
            fp[e.type] = fp.get(e.type, 0) + 1
    types = sorted(set(tp) | set(fp) | set(fn))
    out = {t: _metrics(t, tp.get(t, 0), fp.get(t, 0), fn.get(t, 0), lat.get(t, []), minutes)
           for t in types}
    out["ALL"] = _metrics("ALL", sum(tp.values()), sum(fp.values()), sum(fn.values()),
                          [x for v in lat.values() for x in v], minutes)
    return out


def metrics_dataframe(metrics):
    import pandas as pd
    return pd.DataFrame([vars(m) for m in metrics.values()])
