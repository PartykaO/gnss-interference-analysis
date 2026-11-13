# GNSS trust addition and real receiver records

The trust monitor is **exploratory**, not a calibrated probability of jamming.
States: F = fast check; D = independent deep verification requested;
XJ = suspected interference requiring verification; XS = inconsistent receiver
measurements; XC = inadequate satellite coverage. Neither XJ nor XS proves an attacker.

## Import of actual recordings

- Keep originals outside git, e.g. `data/raw/` (ignored by .gitignore).
- Record receiver/antenna, sample rate, time basis, GNSS band, firmware and
  whether the first calibration window was clean.
- C/N0 must be in dB-Hz **per satellite**, elevation in **radians**.
- The AGC input `a` is a **receiver-calibrated dB change**, not raw AGC counter.
- `pl` is protection level in metres; do not treat HDOP as PL or equate
  horizontal accuracy estimate with a guaranteed bound.
- `energy` is the remaining fraction, in (0,1]; document its source.
- Deep-analysis outcomes must be obtained from a separate independent model;
  never derive a verdict from labels in `scenario.json`.

## Specialized Jammertest parser (experimental)

Requires: `python -m pip install '.[experiments]'`

First inspect **the raw archive schema**:

```bash
python experiments/process_jammertest.py inspect data/raw/GNSS_DATASET_JAMMING_SPOOFING.tar.gz --out outputs/schema
```

The parser was authored without access to the raw Jammertest recordings.
Column inference, time synchronization, antenna-specific baseline, AGC sign,
PL proxy, and scenario annotations must be verified against source recordings
before interpreting results. This is not evidence of independent validation.

The original archive's Monte Carlo results are synthetic; do not present
them as measurements. Independent clean and attack recordings are still needed.
