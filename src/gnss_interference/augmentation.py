"""Controlled nonphysical GNSS observable perturbations on authentic GPS measurements.

Outputs are NOT actual jammer/spoofer events, independently recorded flights,
or measured AGC/elevation/protection levels.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

SCENARIOS = ("attenuation", "satellite_loss", "intermittent", "combined")


@dataclass(frozen=True)
class Config:
    onset_s: float
    duration_s: float
    severity_db: float = 8.0
    loss_fraction: float = 0.6
    ramp_s: float = 5.0
    seed: int = 20261114

    def validate(self):
        if not all(math.isfinite(x) for x in
                   (self.onset_s, self.duration_s, self.severity_db,
                    self.loss_fraction, self.ramp_s)):
            raise ValueError("Injection parameters must be finite")
        if min(self.onset_s, self.severity_db, self.ramp_s) < 0 or self.duration_s <= 0:
            raise ValueError("Invalid onset, duration, severity or ramp")
        if not 0 <= self.loss_fraction <= 1:
            raise ValueError("loss_fraction outside [0,1]")
        return self


def read_source(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        if not r.fieldnames or not {"time_s", "cn0", "satellites"}.issubset(r.fieldnames):
            raise ValueError("Missing time_s,cn0,satellites input columns")
        for index, row in enumerate(r, 2):
            t = float(row["time_s"])
            sat = float(row["satellites"])
            raw = (row.get("cn0") or "").strip()
            cn0 = float(raw) if raw else None
            if (not math.isfinite(t) or not math.isfinite(sat) or sat < 0 or
                (cn0 is not None and not math.isfinite(cn0))):
                raise ValueError(f"Invalid measured row {index}")
            if rows and t <= rows[-1]["time_s"]:
                raise ValueError("Timestamps must strictly increase")
            rows.append(dict(time_s=t, cn0=cn0, satellites=sat))
    if not rows:
        raise ValueError("Empty measurement session")
    return rows


def envelope(t, config):
    delta = t - config.onset_s
    if delta < 0 or delta >= config.duration_s:
        return 0.0
    return min(1.0, delta / config.ramp_s) if config.ramp_s else 1.0


def augment_rows(measured, scenario, config):
    config.validate()
    if scenario not in SCENARIOS:
        raise ValueError("Unsupported scenario: " + str(scenario))
    rng = random.Random(config.seed)
    out = []
    for row in measured:
        t, cn0, sat = row["time_s"], row["cn0"], row["satellites"]
        level = envelope(t, config)
        if scenario == "intermittent" and int(math.floor(t-config.onset_s)) % 5 >= 3:
            level = 0.0
        reduce_cn0 = scenario in ("attenuation", "intermittent", "combined")
        lose_channels = scenario in ("satellite_loss", "combined")
        drop_db = config.severity_db * level if reduce_cn0 and cn0 is not None else 0.0
        lost = 0
        if lose_channels and level > 0:
            # Tracking channel count proxy, NOT true distinct satellite count.
            lost = sum(rng.random() < level*config.loss_fraction
                       for _ in range(max(0, int(round(sat)))))
        after_sat = max(0.0, sat-lost)
        after_cn0 = None if cn0 is None or after_sat <= 0 else cn0-drop_db
        out.append({
            "time_s":t, "cn0":after_cn0, "satellites":after_sat,
            "source_cn0":cn0, "source_satellites":sat,
            "injection_active":int(level > 0),
            "injection_intensity":level,
            "injected_cn0_drop_db":drop_db,
            "injected_channel_loss":lost,
            "injection_type":scenario if level > 0 else "none"
        })
    return out


def process_file(source, destination, scenario, config):
    source, destination = Path(source), Path(destination)
    original = read_source(source)
    rows = augment_rows(original, scenario, config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        for row in rows:
            w.writerow({k: "" if v is None else v for k,v in row.items()})
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    record = {
        "source_name": source.name,
        "source_sha256": digest,
        "source_status": "authentic-source receiver observables (per Aissou provenance)",
        "injection_status": "nonphysical algorithmic impairment",
        "scenario": scenario,
        "parameters": vars(config),
        "total_epochs": len(rows),
        "injection_active_epochs": sum(r["injection_active"] for r in rows),
        "output": destination.name,
        "physical_attack": False,
        "physical_flight": False,
        "independent_capture": False,
        "attack_labels": "algorithmic injection windows only",
        "not_available": ["AGC", "satellite_elevation", "protection_level"]
    }
    destination.with_suffix(".json").write_text(
        json.dumps(record, indent=2), encoding="utf-8")
    return record


def build_collection(source_dir, output_dir, *, seed=20261114, min_epochs=65):
    source_dir, output_dir = Path(source_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = []
    for source in sorted(source_dir.glob("session_*.csv")):
        rows = read_source(source)
        last = rows[-1]["time_s"]
        if len(rows) < min_epochs or last < 55:
            continue
        onset = max(35.0, round(last*0.45))
        duration = min(25.0, last-onset-5)
        if duration < 10:
            continue
        control = output_dir/"control"/source.name
        control.parent.mkdir(parents=True, exist_ok=True)
        control.write_bytes(source.read_bytes())
        for idx, (name, db, frac) in enumerate([
            ("attenuation", 8.0, 0.0),
            ("satellite_loss", 0.0, 0.65),
            ("intermittent", 9.0, 0.0),
            ("combined", 8.0, 0.5)
        ]):
            cfg = Config(onset, duration, db, frac, 5.0, seed+idx)
            output.append(process_file(source, output_dir/name/source.name, name, cfg))
    (output_dir/"experiment_manifest.json").write_text(
        json.dumps({
            "total_scenarios":len(output),
            "source_sessions":len(output)//len(SCENARIOS),
            "source":"authentic measured GPS + explicitly injected nonphysical degradation",
            "calibration_warning":"Unmodified prefix not certified free of real anomalies",
            "session_warning":"Timing segments do not establish independent acquisitions",
            "scenarios":output
        },indent=2), encoding="utf-8")
    return output


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source_dir", type=Path)
    p.add_argument("--out", type=Path, default=Path("data/private/augmented"))
    p.add_argument("--seed", type=int, default=20261114)
    p.add_argument("--min-epochs", type=int, default=65)
    a=p.parse_args(argv)
    rows=build_collection(a.source_dir,a.out,seed=a.seed,min_epochs=a.min_epochs)
    print(json.dumps({"base_sessions":len(rows)//4,"scenarios":len(rows)},indent=2))


if __name__=="__main__":
    main()
