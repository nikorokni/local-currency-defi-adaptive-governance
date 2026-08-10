# Results validation

## Automated checks

`./run_all.sh` performs the following checks after regenerating every output:

1. exactly seven PNG figures exist and each exceeds 1,000 by 600 pixels;
2. both Python sources compile with warnings treated as errors;
3. six unit tests cover deterministic block sampling, 39-window construction, exact monthly-return preservation, one-source manipulation resistance, breaker comparative statics, and finite bounded accounting;
4. LaTeX compiles twice with `-halt-on-error`;
5. the final log contains no undefined references, undefined citations, or fatal errors; and
6. Ghostscript rewrites the PDF with embedded/prepress-compatible resources.

## Distribution-level validation

`results/validation_checks.csv` asserts:

- eight architecture-currency rows in the main experiment;
- 39 realised windows per architecture and currency;
- lower mean oracle error for the adaptive multi-oracle design than for the static single-oracle benchmark;
- lower bad-debt probability for the full architecture in both currencies;
- weakly lower severe-depeg probability when the breaker is added; and
- finite numeric values in every main and robustness output.

## Main anchors

The deterministic anchors in `results/validation_anchors.json` include:

- seed `20260810`;
- 6,000 paths per main currency-architecture cell;
- 480 six-hour steps, or 120 days, per path;
- 39 historical windows per currency;
- ARS static bad-debt probability `0.154`;
- ARS full-architecture bad-debt probability `0.0028333333`;
- TRY static severe-depeg probability `1.0`;
- TRY full-architecture severe-depeg probability `0.25`;
- full-architecture pause shares near 28% for ARS and 29% for TRY; and
- exact SHA-256 checksums for both raw FX snapshots and the processed panel.

These values are validation anchors for this release, not universal facts. Any intentional model or calibration change should regenerate the anchors, figures, tables, PDF, and documentation together.

## Interpretation checks

The empirical panel is observed; the high-frequency arrival time, official/parallel gap, attack process, DEX depth, arbitrage capacity, borrower demand, and controller gains are scenario assumptions. The paper consistently labels bootstrap outcomes as counterfactual probabilities conditional on those assumptions. It does not call them forecasts, causal estimates, or live-protocol incident rates.

