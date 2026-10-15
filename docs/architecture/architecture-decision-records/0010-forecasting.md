# ADR-0010: Forecasting

## Decision
- Baselines:
  - Empirical overlapping-window horizon distribution.
  - Stationary block bootstrap with a recorded seed.
  - Zero-drift and historical-mean baselines.
  - A yield-carry scenario model for debt (YTM − expenses ± duration × Δy).
- Outputs are labelled **scenario ranges**, never "probabilities". Calibrated-probability language requires a coverage test to pass first.
- Validation: rolling-origin walk-forward with purging and an embargo sized to the horizon. Metrics: pinball loss, interval coverage, CRPS, MAE and RMSE.
- A model is promoted only if it beats the baseline under the Diebold–Mariano test **with the Harvey–Leybourne–Newbold small-sample correction**. Otherwise the baseline stays.
- A survivorship-bias banner is shown on category statistics until point-in-time coverage of closed schemes is confirmed.

## Evidence
validation-methodology.md (DM example: p=0.047 raw → 0.057 corrected; baseline retained).
