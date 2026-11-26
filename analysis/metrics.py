"""Stage 4: detection metrics per event type, from MatchResults.

Uses MatchResults from Stage 3 to evaluate how accurately the system detects events.

Calculates true positives (TP), false positives (FP), false negatives (FN), precision, recall, and their 95% Wilson confidence intervals. Also measures false alarms per minute and detection latency (median and IQR, in milliseconds).

Undefined metrics are reported as None, not 0. For example, recall is undefined when no ground-truth labels exist for an event type.

For negative-control trials (where no events should occur), false alarms per minute is particularly important.

Multiple trials can be pooled by providing their MatchResults and recording durations in milliseconds, in the same order. 
"""

import math
import pandas as pd
from dataclasses import dataclass, asdict


def wilson(k, n, z=1.96):
    """Calculate the 95% Wilson confidence interval."""
    if n == 0:
        return None

    p = k / n
    d = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / d
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d

    return max(0, center - margin), min(1, center + margin)


def percentile(values, q):
    """Calculate a percentile."""
    if not values:
        return None

    values = sorted(values)
    pos = q * (len(values) - 1)
    low = math.floor(pos)
    high = math.ceil(pos)

    return values[low] + (values[high] - values[low]) * (pos - low)


@dataclass
class TypeMetrics:
    type: str
    tp: int
    fp: int
    fn: int
    precision: float
    precision_ci: tuple
    recall: float
    recall_ci: tuple
    false_alarms_per_min: float
    latency_median_ms: float
    latency_q1_ms: float
    latency_q3_ms: float


def calculate_metrics(name, tp, fp, fn, latencies, minutes):
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None

    return TypeMetrics(
        type=name,
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        precision_ci=wilson(tp, tp + fp),
        recall=recall,
        recall_ci=wilson(tp, tp + fn),
        false_alarms_per_min=fp / minutes if minutes else None,
        latency_median_ms=percentile(latencies, 0.5),
        latency_q1_ms=percentile(latencies, 0.25),
        latency_q3_ms=percentile(latencies, 0.75),
    )


def compute_metrics(results, durations_ms):
    """Calculate metrics for each event type and all events combined."""

    if len(results) != len(durations_ms):
        raise ValueError("Input lengths must match.")

    minutes = sum(durations_ms) / 60000

    tp, fp, fn = {}, {}, {}
    latencies = {}

    for result in results:

        for match in result.matches:
            event = match.label.type
            tp[event] = tp.get(event, 0) + 1
            latencies.setdefault(event, []).append(match.latency_ms)

        for label in result.false_negatives:
            fn[label.type] = fn.get(label.type, 0) + 1

        for event in result.false_positives:
            fp[event.type] = fp.get(event.type, 0) + 1

    event_types = sorted(set(tp) | set(fp) | set(fn))

    metrics = {}

    for event in event_types:
        metrics[event] = calculate_metrics(
            event,
            tp.get(event, 0),
            fp.get(event, 0),
            fn.get(event, 0),
            latencies.get(event, []),
            minutes
        )

    # Calculate overall metrics
    metrics["ALL"] = calculate_metrics(
        "ALL",
        sum(tp.values()),
        sum(fp.values()),
        sum(fn.values()),
        [latency for values in latencies.values() for latency in values],
        minutes
    )

    return metrics


def metrics_dataframe(metrics):
    """Convert metrics into a pandas DataFrame."""
    return pd.DataFrame([asdict(metric) for metric in metrics.values()])
