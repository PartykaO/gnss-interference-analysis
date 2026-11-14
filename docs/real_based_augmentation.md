# Real GPS source + injected degradation experiments (2026-11-14)

This workflow uses the **authentic-source GPS receiver recordings**, not
fully synthetic GPS sequences. Only the *controlled impairment* is simulated.
These tests are stress tests and do not demonstrate physical jammer/spoofer
detection rates in flight.

Data source: G. Aissou, *A DATASET for GPS Spoofing Detection on Unmanned
Aerial System*, Mendeley Data version 3 (2022), DOI:
https://doi.org/10.17632/z7dj3yyzt8.3.

## Generate scenarios

First extract the original, authentic-only spreadsheet (not the wide
"Authentic_and_Simulated" workbook):

```bash
python -m gnss_interference.gps_xlsx extract \
  data/raw/GPS_Raw_Data_Authentic_Data_3D_8_Channels.xlsx \
  --out data/private/gps_authentic --bucket-s 1
```

Then generate paired, labeled counterfactual scenarios:

```bash
python -m gnss_interference.augmentation data/private/gps_authentic \
  --out data/private/gnss_augmentation --seed 20261114 --min-epochs 65
```

Four scenarios per eligible time segment:
1. `attenuation`: a ramped 8 dB decrease of observed C/N0;
2. `satellite_loss`: seeded Bernoulli thinning of the active **channel-count
   proxy**, with up to 65% nominal loss;
3. `intermittent`: 9 dB change with a 3-second-on / 2-second-off cycle;
4. `combined`: 8 dB C/N0 change and up to 50% channel thinning.

The onset is placed no earlier than 35 s. The exposure duration is up
to 25 s, with a 5-second ramp and final non-perturbed recovery samples.

The saved dataset contains `control/` unchanged source CSVs;
four scenario subdirectories with fields `time_s, cn0, satellites,
source_cn0, source_satellites, injection_active, injection_intensity,
injected_cn0_drop_db, injected_channel_loss, injection_type`;
one JSON provenance file per scenario; and a global manifest.

CRITICAL SCIENTIFIC LIMITATIONS:
- `injection_active` marks a **created perturbation**, not a measured physical
  jamming, spoofing, or RF interference event.
- Zero active channels results in *missing* C/N0, not 0 dB-Hz.
- `satellites` in source export is a count of tracking channels, not
  independently deduplicated satellite IDs.
- Baseline segments are unmodified, not certified clean.
- Source receiver-time segments are not verified independent flight trials.
- There is no measured AGC, elevation, protection level, or UAV flight path.
  Do not fabricate these features or report full trust-model validation.
- Source-derived sessions and all augmentations of those sessions must stay
  together when splitting train/validation/test. Do not split by augmented row.
- Keep measured source and generated data in `data/private/`, outside Git.

For reproducibility, retain original files, input SHA-256, documented seed,
parameters, and source dataset license/attribution. A clean synthetic
fixture is used for the unit tests only.
