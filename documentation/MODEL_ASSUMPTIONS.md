# Model assumptions and interpretation

## Scope

The code is a mechanism-design stress laboratory for a hypothetical ARS- or TRY-denominated DeFi lending protocol collateralised by ETH. It compares architectures under identical market paths. It does not claim that the simulated controller is production-safe or that the outputs estimate losses for a named live protocol.

## Time and path construction

- Horizon: four 30-day months, evaluated in six-hour intervals (480 steps).
- Main experiment: 6,000 circular two-month moving-block bootstrap paths per currency and architecture.
- Historical replay: all 39 overlapping four-month windows in the 42-return calibration sample.
- Within-month bridge: simulated six-hour returns sum exactly to each bootstrapped monthly FX and ETH return.
- Shock timing: 60% of an adverse monthly movement is assigned to a random six-hour interval; the remaining bridge is mean-corrected.
- Fixed seed: `20260810`, with documented deterministic offsets by experiment and currency.

## Price domains and oracle feeds

`lcu_usd` is the market USD value of one local-currency unit; its inverse is local-currency units per USD. The model distinguishes:

1. an official FX feed with a configurable delay and an official/parallel-rate gap;
2. a DEX execution quote affected by the endogenous secondary-market discount;
3. an independent reference feed with one-step latency and small measurement noise.

The static benchmark composes the official FX feed with a thin-DEX ETH collateral quote. During a manipulation episode, the DEX collateral quote is biased upward for four six-hour steps. The multi-oracle design takes the cross-source median separately for the LCU and ETH legs and monitors the log range of collateral-to-debt ratios.

The official/parallel gap is a scenario state, not a directly observed historical series. Its target rises with monthly depreciation and its short-run value reacts to abrupt currency moves. This choice is explicit because no single, legally accessible, methodologically consistent parallel-market series exists for both countries and the entire study window.

## Lending book

- Initial debt: 0.62 initial debt-ceiling units.
- Eight borrower tranches with fixed initial weights and collateralisation ratios from 153% to 270%.
- Interest accrues every six hours in local-currency debt units.
- Baseline draw demand is 0.18% of the initial ceiling per step and falls exponentially as the borrowing rate rises.
- A manipulation episode adds opportunistic draw demand. Multi-oracle borrowers still post collateral against the robust price; the single-oracle benchmark can admit under-collateralised exposure.
- New issuance is sold into the DEX. Discount persistence, depth, depreciation-linked background conversion, and finite arbitrage capacity jointly determine the DEX basis.

## Liquidation and loss

Positions are liquidated when the observed collateralisation ratio falls below the current threshold. Settlement occurs at contemporaneous true prices, with a haircut that rises with EWMA volatility and the DEX discount. Bad debt is the positive shortfall of true debt value over haircut-adjusted collateral recovery. A liquidation is labelled unnecessary when true collateralisation exceeds the protocol threshold by more than ten percentage points at the observed liquidation time.

## Automated risk engine

The composite risk score is a bounded function of:

- EWMA volatility of the ETH/LCU collateral-to-debt price ratio;
- DEX discount;
- cross-source price disagreement; and
- utilisation above 72%.

The engine maps this score to targets for the annual borrowing rate, debt ceiling, and liquidation ratio. Each parameter has a hard domain and a per-step rate limit. The delayed-DAO benchmark computes the same targets but applies them after 48 hours.

## Circuit breaker

The breaker activates on a DEX discount above 6.5%, source disagreement above 14%, or six-hour EWMA volatility above 10%. Activation pauses new borrowing for at least four steps (24 hours). Repayments and collateral top-ups remain permitted. This asymmetry prevents the safety mechanism itself from trapping borrowers.

## Outcomes and thresholds

- Bad-debt event: cumulative bad debt exceeds 0.001 initial-ceiling units.
- Severe depeg: maximum DEX discount exceeds 10%.
- Deep-depeg time share: fraction of intervals with a discount above 5%.
- Oracle error: absolute log error in the ETH/LCU price ratio.
- Credit cost: cumulative accepted credit, mean borrowing rate, mean ceiling, and pause share.

All thresholds are design assumptions and are varied indirectly through the latency, basis, attack, delay, and controller-ablation exercises. They should not be interpreted as universal optimal values.

