"""Simple conservative anomaly scoring over GNSS receiver observables.

Not a validated jamming detector. Unusual behaviour can also be caused by
obstruction, multipath, receiver changes, or missing measurements.
"""
from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

SUPPORTED = ("cn0", "agc", "satellites", "hdop")


@dataclass(frozen=True)
class Observation:
    time_s: float
    metrics: dict[str, float]


@dataclass(frozen=True)
class Alarm:
    start_s: float
    confirmed_s: float
    end_s: float | None


def read_csv(path: str | Path, time_column: str = "time_s", columns: dict[str, str] | None = None) -> list[Observation]:
    """Read a monotonically increasing receiver timeline; do not interpolate gaps.

    Mapping example: {'cn0': 'mean_cn0_dbhz', 'agc': 'agc_count'}.
    Missing feature cells are omitted rather than filled with invented values.
    """
    columns = columns or {k: k for k in SUPPORTED}
    if not columns or not set(columns).issubset(SUPPORTED):
        raise ValueError("Only cn0, agc, satellites and hdop can be mapped")
    out: list[Observation] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        if not rdr.fieldnames or time_column not in rdr.fieldnames:
            raise ValueError(f"Missing time column: {time_column}")
        used = {k: v for k, v in columns.items() if v in rdr.fieldnames}
        if not used:
            raise ValueError("None of the requested metric columns exist")
        for row_no, row in enumerate(rdr, 2):
            try:
                t = float(row[time_column])
                if not math.isfinite(t):
                    raise ValueError("nonfinite timestamp")
                m = {}
                for metric, col in used.items():
                    raw = row.get(col, "")
                    if raw is not None and raw.strip() != "":
                        x = float(raw)
                        if math.isfinite(x):
                            m[metric] = x
                if out and t <= out[-1].time_s:
                    raise ValueError("timestamps must increase strictly")
                out.append(Observation(t, m))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid CSV row {row_no}: {exc}") from exc
    if not out:
        raise ValueError("CSV contains no observations")
    return out


def _baseline(records: list[Observation], calibration_s: float, min_count: int) -> tuple[float, dict[str, tuple[float, float]]]:
    if calibration_s <= 0 or min_count < 3:
        raise ValueError("calibration_s must be positive and min_count >= 3")
    cutoff = records[0].time_s + calibration_s
    clean = [r for r in records if r.time_s < cutoff]
    if len(clean) < min_count:
        raise ValueError("Insufficient clean calibration observations")
    ref = {}
    for name in SUPPORTED:
        vals = [r.metrics[name] for r in clean if name in r.metrics]
        if len(vals) >= min_count:
            mid = median(vals)
            mad = median(abs(v - mid) for v in vals)
            # A fixed numerical scale floor prevents division by zero; it is not
            # a physically calibrated receiver noise floor.
            floor = {"cn0": 0.5, "agc": 1.0, "satellites": 1.0, "hdop": 0.2}[name]
            ref[name] = (mid, max(1.4826 * mad, floor))
    if not ref:
        raise ValueError("No feature with sufficient clean calibration observations")
    return cutoff, ref


def score(record: Observation, reference: dict[str, tuple[float, float]]) -> float | None:
    """Maximum one-sided standardised excursion; missing metrics are ignored.

    Decreasing C/N0/satellites and increasing HDOP are suspicious. AGC direction
    depends on the receiver; therefore its absolute change is used as a flag.
    Scores are not probabilities and should not be presented as confidence.
    """
    values = []
    for name, (centre, scale) in reference.items():
        if name not in record.metrics:
            continue
        diff = (record.metrics[name] - centre) / scale
        values.append(abs(diff) if name == "agc" else (diff if name == "hdop" else -diff))
    return max(values) if values else None


def analyse(records: list[Observation], *, calibration_s: float = 30.0,
            threshold: float = 4.0, confirm_samples: int = 3,
            recovery_samples: int = 3, min_calibration_count: int = 5) -> tuple[list[dict], list[Alarm], dict]:
    """Causal confirmation/recovery state machine with fixed clean calibration.

    Event start is the first anomalous observation in a confirmed run;
    confirmation time is the observation at which the Nth anomaly arrives.
    An alarm still active at end of recording has end_s=None.
    """
    if threshold <= 0 or confirm_samples < 1 or recovery_samples < 1:
        raise ValueError("threshold must be >0, confirm/recovery counts >=1")
    cutoff, reference = _baseline(records, calibration_s, min_calibration_count)
    series: list[dict] = []
    alarms: list[Alarm] = []
    streak = 0
    recovered = 0
    run_start = None
    active_start = None
    confirmed_at = None
    for r in records:
        s = score(r, reference)
        eligible = r.time_s >= cutoff
        anomaly = eligible and s is not None and s >= threshold
        if active_start is None:
            if anomaly:
                streak += 1
                if streak == 1:
                    run_start = r.time_s
                if streak >= confirm_samples:
                    active_start = run_start
                    confirmed_at = r.time_s
                    recovered = 0
            else:
                streak = 0
                run_start = None
        else:
            if not anomaly and s is not None:
                recovered += 1
                if recovered >= recovery_samples:
                    alarms.append(Alarm(active_start, confirmed_at, r.time_s))
                    active_start = None
                    confirmed_at = None
                    streak = 0
                    run_start = None
                    recovered = 0
            elif anomaly:
                recovered = 0
        series.append({"time_s": r.time_s, "score": s, "anomaly": bool(anomaly),
                       "alarm_active": active_start is not None,
                       **{f"{k}": r.metrics.get(k) for k in SUPPORTED}})
    if active_start is not None:
        alarms.append(Alarm(active_start, confirmed_at, None))
    metadata = {"calibration_end_s": cutoff, "reference_median_and_scale": reference,
                "threshold": threshold, "confirm_samples": confirm_samples,
                "recovery_samples": recovery_samples,
                "warning": "Exploratory anomaly flags; not validated evidence of intentional jamming."}
    return series, alarms, metadata


def evaluate(alarms: list[Alarm], onset_s: float | None = None,
             end_s: float | None = None) -> dict:
    """Report reference-relative delays; an onset label is not physical jammer-on proof."""
    result = {"confirmed_events": len(alarms)}
    if onset_s is None:
        return result
    valid = [a for a in alarms if a.confirmed_s >= onset_s and (end_s is None or a.confirmed_s <= end_s)]
    result["events_confirmed_within_reference_interval"] = len(valid)
    result["first_confirmation_delay_s"] = (min(a.confirmed_s for a in valid) - onset_s) if valid else None
    result["pre_reference_confirmations"] = sum(a.confirmed_s < onset_s for a in alarms)
    return result


def alarm_dicts(alarms: list[Alarm]) -> list[dict]:
    return [asdict(a) for a in alarms]
