"""Extract provenance-preserving RF features from measured processed CardRF CSV.

CardRF is outdoor UAV/controller RF detection data, NOT GNSS telemetry or
independently labelled GNSS jamming. Input rows: 1024 sampled amplitudes
followed by three categorical labels; no header expected. Respect original
Train/Test folders; avoid splitting windows from the same capture across sets.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


SIGNAL_SAMPLES = 1024
COLUMNS = ("mean", "rms", "std", "peak_abs", "crest_factor",
           "zero_crossing_rate", "mean_abs_diff", "first_half_rms",
           "second_half_rms", "control_label", "device_label",
           "capture_label", "row_index")


def features(values: list[float]) -> list[float]:
    if len(values) != SIGNAL_SAMPLES or any(not math.isfinite(x) for x in values):
        raise ValueError("Expected 1024 finite signal samples")
    n = len(values)
    mean = sum(values) / n
    rms = math.sqrt(sum(x*x for x in values) / n)
    std = math.sqrt(sum((x-mean)**2 for x in values) / n)
    peak = max(abs(x) for x in values)
    zcr = sum((a < 0) != (b < 0) for a,b in zip(values,values[1:])) / (n-1)
    madiff = sum(abs(b-a) for a,b in zip(values,values[1:])) / (n-1)
    half = n//2
    rms1 = math.sqrt(sum(x*x for x in values[:half]) / half)
    rms2 = math.sqrt(sum(x*x for x in values[half:]) / (n-half))
    return [mean, rms, std, peak, peak/rms if rms else 0.0,
            zcr, madiff, rms1, rms2]


def extract(source: str | Path, out: str | Path,
            *, max_rows: int | None = None) -> dict:
    """Stream rows, refuse unverified schema; output only derived features.

    The caller controls the source; never infer that a CSV is a flight log.
    """
    if max_rows is not None and max_rows < 1:
        raise ValueError("max_rows must be positive")
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    labels = Counter()
    n = 0
    with source.open("r", newline="", encoding="utf-8-sig") as inp, target.open("w", newline="", encoding="utf-8") as output:
        reader = csv.reader(inp)
        writer = csv.writer(output)
        writer.writerow(COLUMNS)
        for row in reader:
            if max_rows is not None and n >= max_rows:
                break
            if len(row) != SIGNAL_SAMPLES + 3:
                raise ValueError(f"Row {n+1}: expected 1027 fields, got {len(row)}")
            try:
                nums = [float(item) for item in row[:SIGNAL_SAMPLES]]
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Row {n+1}: malformed RF sample") from exc
            meta = row[-3:]
            if not all(meta):
                raise ValueError(f"Row {n+1}: incomplete labels")
            stats = features(nums)
            writer.writerow([f"{v:.9g}" for v in stats] + meta + [n])
            labels[tuple(meta)] += 1
            n += 1
    h = hashlib.sha256()
    with source.open("rb") as inp:
        for chunk in iter(lambda: inp.read(1024*1024), b""):
            h.update(chunk)
    report = {
        "source_filename": source.name,
        "source_sha256": h.hexdigest(),
        "rows_processed": n,
        "partial_extraction": max_rows is not None,
        "file_structure": "1024 RF samples + 3 categorical label strings",
        "source_type": "measured CardRF processed RF signal; verify source provenance",
        "not_a_gnss_jamming_or_flight_telemetry_dataset": True,
        "provenance_warning": "Protect Train/Test file split; capture-level independence is unverified",
        "labels": [{"control":k[0],"device":k[1],"capture":k[2],"rows":v}
                   for k,v in sorted(labels.items())],
    }
    target.with_suffix(".manifest.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",type=Path)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--max-rows",type=int,default=None)
    args=p.parse_args(argv)
    print(json.dumps(extract(args.source,args.out,max_rows=args.max_rows),indent=2))


if __name__ == "__main__":
    main()
