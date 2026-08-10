# Data and literature provenance

## Empirical model inputs

The common monthly panel covers January 2020 through July 2023. FX observations are monthly averages in local-currency units per US dollar from OECD Main Economic Indicators, distributed by the Federal Reserve Bank of St. Louis (FRED). ETH/USD is the Coin Metrics community series preserved in the companion solvency package.

| File | Series and role | SHA-256 |
|---|---|---|
| `data/raw_fx/ars_usd_fred.csv` | [ARGCCUSMA02STM](https://fred.stlouisfed.org/series/ARGCCUSMA02STM), ARS per USD | `1dacf0b03e50660e0bbd819e3b73f6783576517a8d0cf9ac2559dbb92d0f455d` |
| `data/raw_fx/try_usd_fred.csv` | [CCUSMA02TRM618N](https://fred.stlouisfed.org/series/CCUSMA02TRM618N), TRY per USD | `51d90a2eb45a989dcc078e04dacfcb06637026e90a3ead8d8290e8a61a32aad4` |
| `data/processed/joint_monthly_market_panel.csv` | 43 levels and 42 joint FX/crypto changes | `5615ff2076e65cea9fe46bf8752ae28210fd235c8b7817663be24e20500914ce` |

The processed panel is copied unchanged from the companion solvency and peg-stability packages to preserve cross-paper comparability. The first paper's public MakerDAO ETH-A draw events motivate borrower conversion flow but are not treated as observed demand for this experiment.

## Primary mechanism sources

- [Chainlink Data Feeds documentation](https://docs.chain.link/data-feeds): update heartbeats, deviation thresholds, timestamps, freshness checks, and application-level fallback modes.
- [Maker/Sky executive vote, 4 October 2024](https://vote.makerdao.com/executive/template-executive-vote-stability-scope-parameter-changes-lite-psm-usdc-a-phase-3-final-setup-aave-lido-market-spark-usds-ddm-activation-wbtc-legacy-vaults-parameter-changes-october-4-2024): governance-set risk parameters and a reported 16-hour governance security-module delay.
- [Aave reserve documentation](https://aave.com/docs/aave-v3/concepts/reserve) and [risk documentation](https://aave.com/docs/resources/risks): borrow caps, supply caps, LTV, liquidation thresholds, and DAO risk-service monitoring.
- Eskandari, Salehi, Gu, and Clark (2021), [“SoK: Oracles from the Ground Truth to Market Manipulation”](https://arxiv.org/abs/2106.00667): oracle trust models and manipulation surfaces.
- Xu, Feng, Perez, and Livshits (2025), [“Auto.gov: Learning-based Governance for Decentralized Finance”](https://arxiv.org/abs/2302.09551): learning-based governance under oracle attacks.
- Bastankhah et al. (2024), [“Thinking Fast and Slow: Data-Driven Adaptive DeFi Borrow-Lending Protocol”](https://doi.org/10.4230/LIPIcs.AFT.2024.27): fast interest control and slower collateral planning.
- Chiu et al. (2023), [“On the Fragility of DeFi Lending”](https://doi.org/10.34989/swp-2023-14): rigid parameters, feedback, and flexible contract updates.
- Chaudhary, Kozhan, and Viswanath-Natraj (2023), [“Interest Rate Rules in Decentralized Finance: Evidence from Compound”](https://doi.org/10.4230/OASIcs.Tokenomics.2022.5): utilisation-linked rates and governance-set slopes.
- Gudgeon et al. (2020), [“DeFi Protocols for Loanable Funds”](https://doi.org/10.1145/3419614.3423254): lending-protocol rate and liquidity mechanisms.
- Sadeghi and Feinstein (2026), [“Liquidation Dynamics in DeFi and the Role of Transaction Fees”](https://arxiv.org/abs/2602.12104): liquidation, oracle extractable value, and the latency/manipulation trade-off.
- Aldasoro, Beltran, and Grinberg (2026), [“Stablecoin Flows and Spillovers to FX Markets”](https://www.bis.org/publ/work1340.htm): stablecoin-based FX parity deviations and constrained intermediary capital.
- Künsch (1989), [“The Jackknife and the Bootstrap for General Stationary Observations”](https://doi.org/10.1214/aos/1176347265): moving-block bootstrap.

The manuscript provides complete citation context and additional DeFi, stablecoin, and control references.

## Reproducibility and licensing

No proprietary API, private key, wallet, or paid dataset is required. Original code and text are MIT-licensed. FRED/OECD data, Coin Metrics data, and the Springer Nature class retain their own source terms and are not relicensed by this repository.

