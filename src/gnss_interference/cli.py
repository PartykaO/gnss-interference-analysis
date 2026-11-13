"""Command-line interface; no automatic downloads, network calls or file uploads."""
import argparse
import csv
import json
from pathlib import Path

from .core import SUPPORTED, alarm_dicts, analyse, evaluate, read_csv


def main(argv=None):
    p = argparse.ArgumentParser(description="Exploratory GNSS receiver anomaly and event analysis")
    p.add_argument("input_csv", help="CSV with a monotonic numeric time column")
    p.add_argument("--time-column", default="time_s")
    for name in SUPPORTED:
        p.add_argument(f"--{name}-column", default=name)
    p.add_argument("--calibration-s", type=float, default=30)
    p.add_argument("--threshold", type=float, default=4)
    p.add_argument("--confirm-samples", type=int, default=3)
    p.add_argument("--recovery-samples", type=int, default=3)
    p.add_argument("--onset-s", type=float, default=None, help="Annotated reference onset, not guaranteed physical onset")
    p.add_argument("--end-s", type=float, default=None)
    p.add_argument("--output", default="outputs")
    p.add_argument("--plot", action="store_true", help="Requires optional matplotlib installation")
    a = p.parse_args(argv)
    mapping = {name: getattr(a, name + "_column") for name in SUPPORTED}
    rows = read_csv(a.input_csv, a.time_column, mapping)
    series, alarms, info = analyse(rows, calibration_s=a.calibration_s,
                                   threshold=a.threshold, confirm_samples=a.confirm_samples,
                                   recovery_samples=a.recovery_samples)
    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "scores.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(series[0]))
        writer.writeheader()
        writer.writerows(series)
    report = {"input_rows": len(rows), "events": alarm_dicts(alarms),
              "evaluation": evaluate(alarms, a.onset_s, a.end_s), "settings": info}
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if a.plot:
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise SystemExit("Install optional plotting dependency: pip install '.[plots]'") from exc
        fig, ax = plt.subplots(figsize=(10, 3.5))
        ax.plot([r["time_s"] for r in series], [r["score"] for r in series], label="Anomaly score")
        ax.axhline(a.threshold, linestyle="--", label="Threshold")
        for alarm in alarms:
            ax.axvline(alarm.confirmed_s, alpha=0.6, linestyle=":")
        ax.set(xlabel="Source time (s)", ylabel="Relative anomaly score")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "scores.png", dpi=160)
        plt.close(fig)
    print(json.dumps({"output": str(out), "evaluation": report["evaluation"]}, indent=2))


if __name__ == "__main__":
    main()
