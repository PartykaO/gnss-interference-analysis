"""Paired comparison on GNSS real-source / nonphysical injection experiment.

Python 3.10+, standard library only. This evaluates imposed observable changes,
NOT physically recorded jammer/spoofer attacks or UAV flight performance.
"""
import argparse
import csv
import io
import json
import math
import statistics as stats
import zipfile
from pathlib import Path

METHODS = ("cn0_4db", "cusum_cn0", "core_z4", "dual_observable")
SCENARIOS = ("attenuation", "satellite_loss", "intermittent", "combined")
CALIBRATION_S = 30.0


def parse(data):
    out = []
    for row in csv.DictReader(io.StringIO(data.decode("utf-8-sig"))):
        t = float(row["time_s"])
        cn0 = float(row["cn0"]) if row["cn0"].strip() else None
        n = float(row["satellites"])
        if out and t <= out[-1]["time_s"]:
            raise ValueError("Receiver time is not strictly increasing")
        out.append({"time_s": t, "cn0": cn0, "satellites": n,
                    "injection_active": int(row.get("injection_active", "0"))})
    return out


def reference(rows):
    prefix = [r for r in rows if r["time_s"] < rows[0]["time_s"] + CALIBRATION_S]
    out = {}
    for name, floor in (("cn0", 0.5), ("satellites", 1.0)):
        vals = [r[name] for r in prefix if r[name] is not None]
        if len(vals) >= 5:
            centre = stats.median(vals)
            scale = max(1.4826 * stats.median(abs(x - centre) for x in vals), floor)
            out[name] = (centre, scale)
    if not out:
        raise ValueError("Not enough calibration measurements")
    return out


def events(rows, method, ref):
    """Causal flags and 3-sample confirmation / 3-sample recovery."""
    assert method in METHODS
    centre_cn0 = ref.get("cn0", (None,))[0]
    centre_n = ref.get("satellites", (None,))[0]
    consecutive = recovered = 0
    active = False
    cumulative = 0.0
    alarms = []
    for row in rows:
        t, c, n = row["time_s"], row["cn0"], row["satellites"]
        if t < CALIBRATION_S:
            continue
        if method == "cn0_4db":
            observed = c is not None and centre_cn0 is not None
            flag = observed and centre_cn0 - c >= 4.0
        elif method == "cusum_cn0":
            observed = c is not None and centre_cn0 is not None
            if observed:
                cumulative = max(0.0, cumulative + centre_cn0 - c - 1.0)
            flag = observed and cumulative >= 10.0
            if observed and c >= centre_cn0 - 0.5 and not active:
                cumulative = 0.0
        elif method == "core_z4":
            observed = c is not None or n is not None
            scores = []
            if c is not None and "cn0" in ref:
                scores.append((ref["cn0"][0] - c) / ref["cn0"][1])
            if n is not None and "satellites" in ref:
                scores.append((ref["satellites"][0] - n) / ref["satellites"][1])
            flag = bool(scores and max(scores) >= 4.0)
        else:
            observed = c is not None or n is not None
            flag = ((centre_cn0 is not None and c is not None and centre_cn0 - c >= 4.0)
                    or (centre_n is not None and n is not None and centre_n - n >= 2.0))
        if not observed:
            consecutive = recovered = 0
            continue
        if not active:
            consecutive = consecutive + 1 if flag else 0
            if consecutive >= 3:
                alarms.append(t)
                active = True
                recovered = 0
        else:
            recovered = recovered + 1 if not flag else 0
            if recovered >= 3:
                active = False
                consecutive = recovered = 0
                if method == "cusum_cn0":
                    cumulative = 0.0
    return alarms


def evaluate(archive, destination):
    """Use matching controls; only injection labels define reporting windows."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("experiment_manifest.json"))
        cases = manifest["scenarios"]
        sessions = sorted({c["source_name"] for c in cases})
        if len(cases) != 64 or len(sessions) != 16:
            raise ValueError("Not the expected fixed 64-case benchmark")
        rows_out, controls_out = [], []
        for session in sessions:
            original = parse(z.read("control/" + session))
            ref = reference(original)
            original_events = {method: events(original, method, ref) for method in METHODS}
            for method in METHODS:
                controls_out.append({
                    "source": session, "method": method,
                    "control_events": len(original_events[method]),
                    "control_exposure_s": max(0.0, original[-1]["time_s"] - CALIBRATION_S)})
            for case in (c for c in cases if c["source_name"] == session):
                scenario = case["scenario"]
                changed = parse(z.read(scenario + "/" + session))
                if len(changed) != len(original) or any(a["time_s"] != b["time_s"] for a, b in zip(changed, original)):
                    raise ValueError("Changed and original epochs are not paired")
                times = [r["time_s"] for r in changed if r["injection_active"]]
                if not times:
                    raise ValueError("No injection-active epochs")
                start, end = min(times), max(times)
                for method in METHODS:
                    observed = events(changed, method, ref)
                    matched = [t for t in observed if start <= t <= end]
                    paired = [t for t in original_events[method] if start <= t <= end]
                    rows_out.append({
                        "source": session, "scenario": scenario, "method": method,
                        "detected_by_10s": int(any(t <= start + 10 for t in matched)),
                        "detected_by_end": int(bool(matched)),
                        "delay_s": matched[0] - start if matched else "",
                        "paired_control_events_in_window": len(paired),
                        "control_quiet_in_window": int(not paired),
                        "false_pre": sum(CALIBRATION_S <= t < start for t in observed),
                        "false_post": sum(t > end for t in observed),
                        "injection_start_s": start, "injection_end_s": end})
        def write(name, entries):
            with (destination / name).open("w", newline="", encoding="utf-8") as fp:
                w = csv.DictWriter(fp, fieldnames=list(entries[0]))
                w.writeheader()
                w.writerows(entries)
        write("case_metrics.csv", rows_out)
        write("control_metrics.csv", controls_out)
        summary = []
        for scenario in SCENARIOS:
            for method in METHODS:
                r = [x for x in rows_out if x["method"] == method and x["scenario"] == scenario]
                quiet = [x for x in r if x["control_quiet_in_window"]]
                delays = [x["delay_s"] for x in r if x["delay_s"] != ""]
                summary.append({
                    "scenario": scenario, "method": method, "n": len(r),
                    "detected_by_10s": sum(x["detected_by_10s"] for x in r),
                    "detected_by_end": sum(x["detected_by_end"] for x in r),
                    "median_delay_s_detected_only": stats.median(delays) if delays else "",
                    "quiet_controls": len(quiet),
                    "detected_when_control_quiet": sum(x["detected_by_end"] for x in quiet),
                    "matched_control_events_in_window": sum(x["paired_control_events_in_window"] for x in r)})
        write("method_summary.csv", summary)
        control_summary = []
        for method in METHODS:
            rr = [r for r in controls_out if r["method"] == method]
            n = sum(r["control_events"] for r in rr)
            hours = sum(r["control_exposure_s"] for r in rr) / 3600
            control_summary.append({"method": method, "events": n,
                                    "exposure_h": hours,
                                    "descriptive_events_per_h": n / hours if hours else None})
        write("control_summary.csv", control_summary)
        (destination / "summary.json").write_text(json.dumps({
            "cases": len(cases), "segments": len(sessions),
            "analyses": len(rows_out), "method_summary": summary,
            "control_summary": control_summary,
            "limitations": "Nonphysical injected perturbations, potentially dependent real receiver segments, no GNSS flight attack ground truth; no evaluation of full trust monitor without AGC/elevation/PL."
        }, indent=2), encoding="utf-8")
        return summary, control_summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive", type=Path)
    ap.add_argument("--out", type=Path, default=Path("outputs/gnss_comparison_64"))
    args = ap.parse_args()
    summary, controls = evaluate(args.archive, args.out)
    print(json.dumps({"method_summary": summary, "controls": controls}, indent=2))


if __name__ == "__main__":
    main()
