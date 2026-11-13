# GNSS Interference Analysis

An inspectable Python research tool for analysing anomalies in GNSS receiver measurements and reporting confirmed events instead of sample-only classifications. This repository includes original implementation code, tests and a synthetic example; it does not include external datasets or trained models.

## Features

- Read receiver-derived CSV records with explicit column mappings.
- Estimate baseline statistics from a documented clean initial window using median and MAD.
- Score C/N0 decrease, satellite count decrease, HDOP increase, or changes in AGC.
- Require repeated anomalous observations to confirm events and repeated normal observations to recover.
- Export scores.csv and report.json, with optional plots.
- Estimate confirmation delays relative to labelled reference times, **not physical jammer onset**.

**Research limitation:** An anomaly is not proof of intentional GNSS interference. Terrain obstruction, multipath, antenna faults and receiver settings may produce similar effects. Thresholds here are illustrative and have no validated false-alarm guarantees.

## Installation

Python 3.10 or newer:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

For optional plots install `python -m pip install -e '.[plots]'`.

## Example

`examples/sample.csv` is synthetic test data, **not a real GNSS recording**.

```bash
gnss-analyse examples/sample.csv --calibration-s 10 --confirm-samples 3 --recovery-samples 2 --output outputs/demo
```

Example mapping receiver-specific column names:

```bash
gnss-analyse receiver.csv --time-column seconds --cn0-column mean_cn0_dbhz --agc-column agc_count --satellites-column used_sv --hdop-column hdop --calibration-s 30 --output outputs/receiver
```

## Input schema

| Field | Meaning |
| --- | --- |
| time_s | Strictly increasing timestamps in seconds |
| cn0 | Aggregated carrier-to-noise density (dB-Hz), aggregation documented |
| agc | Receiver-specific AGC units |
| satellites | Satellites used for navigation (count) |
| hdop | Horizontal dilution of precision (dimensionless) |

One or more supported metrics are required. Missing data are not imputed. Input times must already be converted to numeric seconds. Do not substitute different quantities for required metrics (HDOP is not position error). Raw RINEX and UBX files need separate, validated adapters.

## Reproducibility

Do not combine independent sessions when calibrating baselines. Original recording provenance, receiver setup, time references and attack annotations must be stored separately. Repeated replays are technical repetitions, not independent captures. Count false alarms against measured clean exposure, and independently measure runtime on the actual target hardware before making UAV suitability claims.

## Files

- `src/gnss_interference/core.py`: data loading, anomaly scores, event confirmation and evaluation
- `src/gnss_interference/cli.py`: command-line interface, CSV/JSON exports and optional plotting
- `tests/test_core.py`: unit tests
- `examples/sample.csv`: synthetic sample
- `pyproject.toml`, `requirements.txt`: installation and dependency information

## Future work

Validate on independent clean and interference receiver recordings with known session/episode boundaries; add separately tested adapters for RINEX and UBX exports; compare event sensitivity, false alarms per hour and resource use.