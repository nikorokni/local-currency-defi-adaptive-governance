# Adaptive Governance and Oracle Architecture for Local-Currency DeFi

Replication package for the working paper:

> Niko Rokni Lamouki, Salma Soofiyan, and Amin Karami (2026), “Adaptive Governance, Oracle Latency, and Automated Risk Engine Design for Local-Currency DeFi Lending Protocols.”

This is the fourth paper in a research sequence on hypothetical local-currency DeFi lending. It replaces three simplifying assumptions in the companion studies—error-free prices, instantaneous parameter changes, and unlimited reaction capacity—with a multi-source oracle, delayed DAO benchmark, bounded automated controller, and circuit breaker.

## Research question

Can an automated risk engine adjust the borrowing rate, debt ceiling, and liquidation ratio quickly enough to contain oracle error, joint FX/collateral shocks, and DEX sell pressure without eliminating useful credit access?

## Design

- Official FX, DEX execution, and independent-reference price domains.
- A three-source log-median oracle and an intentionally fragile single-source benchmark.
- Six-hour risk updates using EWMA volatility, DEX basis, source disagreement, and utilisation.
- Rate-limited controls for the borrowing rate, debt ceiling, and liquidation ratio.
- A circuit breaker that pauses new draws but preserves repayment and collateral top-ups.
- A 48-hour delayed-DAO benchmark and governance-delay sensitivity from 0 to 72 hours.
- Opportunistic borrowing during one-source collateral manipulation episodes.
- 6,000 four-month moving-block bootstrap paths per currency and architecture, 39 realised rolling windows per currency, deterministic seed `20260810`, and six-hour intramonth stress timing.

The model is a transparent counterfactual design experiment. It is not a forecast, audited smart contract, policy recommendation, or evidence from a deployed ARS- or TRY-denominated lending protocol.

## Main results

- In the main bootstrap experiment, the static single-oracle architecture produces bad debt in 15.4% of ARS paths and 14.0% of TRY paths. The adaptive multi-oracle architecture with a breaker reduces those probabilities to 0.28% and 0.20%.
- A severe DEX discount above 10% occurs in every static and 48-hour delayed-DAO path. The full architecture reduces the rate to 0% for ARS and 25% for TRY. Residual TRY failures arise when background conversion pressure alone exceeds the modelled arbitrage capacity.
- The protection is not free. The breaker is active for 28.0% of ARS intervals and 29.1% of TRY intervals, and mean cumulative credit issuance falls from about 0.70 to 0.20–0.22 initial-ceiling units.
- Increasing the one-source attack magnitude from zero to twice the baseline raises static bad-debt probability from 14.4% to 20.4%; the multi-oracle-breaker result remains 0.33% in the pooled sensitivity sample.
- Execution delay is decisive. At 24 hours, severe-depeg probability reaches 100% for ARS and 86% for TRY in the no-breaker controller; by 48 hours it is 100% for both.

## Repository map

| Path | Contents |
|---|---|
| `manuscript/main.tex` | Complete LaTeX manuscript |
| `manuscript/main.pdf` | Compiled paper |
| `analysis/model.py` | Market-path, oracle, lending, controller, and breaker model |
| `analysis/run_analysis.py` | Main analysis, robustness, tables, figures, and validation |
| `data/raw_fx/` | Original FRED/OECD FX snapshots |
| `data/processed/` | Common 43-month joint FX/crypto panel |
| `results/` | Machine-readable main, historical, robustness, and validation outputs |
| `tables/` | Six machine-generated LaTeX tables |
| `figures/` | Seven publication figures |
| `tests/` | Determinism, accounting, oracle, and comparative-statics tests |
| `documentation/` | Source provenance, assumptions, and result validation |

## Reproduce

On a system with Python 3.11+, `pdflatex`, and Ghostscript:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run_all.sh
```

The script regenerates every result, table, and figure; validates the PNG files; compiles the Python sources; runs the unit tests; compiles LaTeX twice; and rejects unresolved citations or references.

## Data provenance

The common calibration panel covers January 2020 through July 2023. ARS and TRY exchange rates are OECD Main Economic Indicators monthly series distributed by FRED; ETH/USD is the Coin Metrics community series inherited from the companion solvency package. Source URLs, checksums, and transformation notes are in [`documentation/SOURCES.md`](documentation/SOURCES.md).

## Companion papers

1. [Inflation-Driven Debt Erosion in Local-Currency DeFi Lending](https://github.com/nikorokni/inflation-driven-debt-erosion-defi)
2. [From Debt Erosion to Protocol Solvency](https://github.com/nikorokni/local-currency-defi-solvency-stress-test)
3. [From Debt Erosion to Peg Stability](https://github.com/nikorokni/local-currency-defi-peg-stability)

## Licence

Original code and text are released under the MIT License. Third-party data and the Springer Nature LaTeX class retain their original terms and provenance.

