# Completed GNSS controlled-degradation comparison (2026-11-14)

## Data and protocol

The user-provided **authentic-source** GPS receiver observations from Aissou
(Mendeley Data DOI 10.17632/z7dj3yyzt8.3) were segmented into 16
receiver-time segments. Four nonphysical controlled perturbation types were
applied to each original trace, yielding 64 labeled altered traces and
16 unchanged paired controls.

Run the GitHub comparator with the user's private archive:

```bash
python -m experiments.compare_gnss_64 \
  data/private/GNSS_real_based_augmentation_64_scenarios.zip \
  --out outputs/gnss_comparison_64
python -m unittest discover -s tests -v
```

The benchmark has four fixed, non-tuned comparators:
1. 4-dB C/N0 drop rule;
2. C/N0 CUSUM, k=1 dB, h=10;
3. standardized maximum one-sided C/N0 and channel-count change with threshold 4;
4. combined 4-dB C/N0 or two tracked-channel loss rule.

Every method shares 30 s initial median/MAD calibration, 3-sample alarm
confirmation, and 3-sample recovery. The timing of a confirmed event is
the 3rd positive sample, not the first abnormal sample. The dataset's
`injection_active` is used for **evaluation only**, never in any
detector's predictions.

## Detection by end of imposed perturbation (out of 16)

| Method | C/N0 attenuation | Channel loss | Intermittent | Combined |
|---|---:|---:|---:|---:|
| 4-dB C/N0 | 16 | 0 | 16 | 16 |
| CUSUM | 14 | 2 | 14 | 14 |
| Standardized max-z | 16 | 5 | 16 | 16 |
| Dual observable | 15 | 10 | 15 | 15 |

On 16 original, unchanged controls (only 0.411944 h in aggregate),
the number of confirmed events was 2, 6, 8, and 6 respectively.
These are descriptive event counts, NOT independently validated false
alarm rates on operational UAV flights.

The exact scenario-level 256-row output, paired control results,
delay summaries, and PNG plots are in the user's private experiment
package `GNSS_experimental_comparison_64_complete.zip`. **Do not**
commit that dataset package or its derived measurement CSVs here.

## Key inference and limitations

Channel-loss detection improves when tracking-channel count is used:
10/16 in the dual-observable rule versus 0/16 for C/N0 alone.
The standardized z-rule and combined rule also showed baseline alerts
on some unchanged controls. Each altered trace must be interpreted
alongside its *own paired original* to avoid calling natural
baseline anomalies successful injection detections.

The source is measured GPS data, but the imposed modifications
are nonphysical and must not be called authentic RF jamming/spoofing.
Receiver-time segments are not proven independent flight campaigns.
No AGC, satellite elevation, receiver protection level, or
verified attack onset is available. Therefore the full
`src/gnss_interference/trust.py` algorithm was NOT validated here.
No quantitative onboard CPU, deadline, or energy claims can be made.
