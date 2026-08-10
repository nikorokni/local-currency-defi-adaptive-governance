"""Adaptive-governance and multi-oracle stress-test primitives.

The model is deliberately transparent.  It is a counterfactual laboratory for a
hypothetical local-currency DeFi lending protocol, not a production controller
and not a forecast of any deployed protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Architecture:
    """Oracle and governance architecture used by the protocol."""

    name: str
    multi_oracle: bool
    adaptive: bool
    circuit_breaker: bool
    governance_delay_hours: int = 0
    official_latency_hours: int = 24
    control_rate: bool = True
    control_ceiling: bool = True
    control_liquidation: bool = True


@dataclass(frozen=True)
class SimulationConfig:
    """Economic and numerical assumptions shared across architectures."""

    step_hours: int = 6
    steps_per_month: int = 120
    horizon_months: int = 4
    initial_debt: float = 0.62
    initial_debt_ceiling: float = 1.0
    initial_rate: float = 0.08
    initial_liquidation_ratio: float = 1.50
    base_draw_per_step: float = 0.0018
    borrower_rate_elasticity: float = 2.4
    dex_depth: float = 0.18
    dex_impact: float = 1.7
    basis_persistence: float = 0.94
    breaker_basis: float = 0.065
    breaker_disagreement: float = 0.140
    breaker_volatility: float = 0.100
    breaker_cooldown_steps: int = 4
    max_rate: float = 1.50
    min_ceiling: float = 0.20
    max_liquidation_ratio: float = 2.20

    @property
    def n_steps(self) -> int:
        return self.steps_per_month * self.horizon_months


@dataclass
class MarketPaths:
    """Common exogenous market environment supplied to every architecture."""

    lcu_usd: np.ndarray
    eth_usd: np.ndarray
    official_gap: np.ndarray
    attack_mask: np.ndarray
    attack_size: np.ndarray
    reference_noise_lcu: np.ndarray
    reference_noise_eth: np.ndarray
    fx_step_log_return: np.ndarray
    eth_step_log_return: np.ndarray

    @property
    def n_paths(self) -> int:
        return self.lcu_usd.shape[0]

    @property
    def n_steps(self) -> int:
        return self.lcu_usd.shape[1] - 1


MAIN_ARCHITECTURES = [
    Architecture(
        name="Static single oracle",
        multi_oracle=False,
        adaptive=False,
        circuit_breaker=False,
        official_latency_hours=24,
    ),
    Architecture(
        name="Delayed DAO",
        multi_oracle=True,
        adaptive=True,
        circuit_breaker=False,
        governance_delay_hours=48,
        official_latency_hours=24,
    ),
    Architecture(
        name="Adaptive multi-oracle",
        multi_oracle=True,
        adaptive=True,
        circuit_breaker=False,
        governance_delay_hours=0,
        official_latency_hours=24,
    ),
    Architecture(
        name="Adaptive multi + breaker",
        multi_oracle=True,
        adaptive=True,
        circuit_breaker=True,
        governance_delay_hours=0,
        official_latency_hours=24,
    ),
]


def moving_block_bootstrap_joint(
    values: np.ndarray,
    n_paths: int,
    horizon: int,
    block_length: int,
    seed: int,
) -> np.ndarray:
    """Circular moving-block bootstrap that preserves cross-series dependence."""

    data = np.asarray(values, dtype=float)
    if data.ndim != 2 or data.shape[0] < 2 or data.shape[1] < 1:
        raise ValueError("values must be a finite two-dimensional panel")
    if np.any(~np.isfinite(data)):
        raise ValueError("values contain non-finite observations")
    if n_paths < 1 or horizon < 1 or block_length < 1:
        raise ValueError("n_paths, horizon, and block_length must be positive")

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(horizon / block_length))
    starts = rng.integers(0, data.shape[0], size=(n_paths, n_blocks))
    out = np.empty((n_paths, n_blocks * block_length, data.shape[1]))
    for block in range(n_blocks):
        offsets = (starts[:, block, None] + np.arange(block_length)) % data.shape[0]
        out[:, block * block_length : (block + 1) * block_length, :] = data[offsets]
    return out[:, :horizon, :]


def historical_joint_windows(values: np.ndarray, horizon: int) -> np.ndarray:
    """All overlapping historical windows from a joint return panel."""

    data = np.asarray(values, dtype=float)
    if data.ndim != 2 or len(data) < horizon:
        raise ValueError("not enough observations for historical windows")
    return np.stack([data[i : i + horizon] for i in range(len(data) - horizon + 1)])


def _bridge_noise(
    rng: np.random.Generator,
    n_paths: int,
    steps: int,
    monthly_sigma: float,
) -> np.ndarray:
    noise = rng.normal(size=(n_paths, steps))
    noise -= noise.mean(axis=1, keepdims=True)
    return noise * monthly_sigma / np.sqrt(steps)


def build_market_paths(
    macro_paths: np.ndarray,
    seed: int,
    config: SimulationConfig | None = None,
    attack_probability: float = 0.22,
) -> MarketPaths:
    """Disaggregate monthly FX/ETH paths to six-hour paths with stress jumps.

    Column zero of ``macro_paths`` is LCU depreciation (LCU per USD change),
    and column one is the ETH/USD return.  The bridge construction exactly
    preserves each bootstrapped monthly return while creating a random
    within-month arrival time for the dominant shock.
    """

    cfg = config or SimulationConfig()
    macro = np.asarray(macro_paths, dtype=float)
    if macro.ndim != 3 or macro.shape[1:] != (cfg.horizon_months, 2):
        raise ValueError(
            f"macro_paths must have shape (paths, {cfg.horizon_months}, 2)"
        )
    if np.any(~np.isfinite(macro)) or np.any(macro[:, :, 0] <= -1.0) or np.any(
        macro[:, :, 1] <= -1.0
    ):
        raise ValueError("invalid macro returns")
    if not 0.0 <= attack_probability <= 1.0:
        raise ValueError("attack_probability must lie in [0, 1]")

    rng = np.random.default_rng(seed)
    n_paths = macro.shape[0]
    n_steps = cfg.n_steps
    fx_log = np.empty((n_paths, n_steps), dtype=float)
    eth_log = np.empty((n_paths, n_steps), dtype=float)

    for month in range(cfg.horizon_months):
        start = month * cfg.steps_per_month
        stop = start + cfg.steps_per_month
        target_fx = -np.log1p(macro[:, month, 0])
        target_eth = np.log1p(macro[:, month, 1])

        fx = target_fx[:, None] / cfg.steps_per_month
        fx = fx + _bridge_noise(
            rng, n_paths, cfg.steps_per_month, monthly_sigma=0.025
        )
        eth = target_eth[:, None] / cfg.steps_per_month
        eth = eth + _bridge_noise(
            rng, n_paths, cfg.steps_per_month, monthly_sigma=0.18
        )

        # Concentrate part of adverse monthly movement in one random interval.
        fx_jump_at = rng.integers(0, cfg.steps_per_month, size=n_paths)
        eth_jump_at = rng.integers(0, cfg.steps_per_month, size=n_paths)
        fx_jump = -0.60 * np.maximum(-target_fx, 0.0)
        eth_jump = 0.60 * np.minimum(target_eth, 0.0)
        rows = np.arange(n_paths)
        fx -= fx_jump[:, None] / max(cfg.steps_per_month - 1, 1)
        eth -= eth_jump[:, None] / max(cfg.steps_per_month - 1, 1)
        fx[rows, fx_jump_at] += fx_jump * cfg.steps_per_month / max(
            cfg.steps_per_month - 1, 1
        )
        eth[rows, eth_jump_at] += eth_jump * cfg.steps_per_month / max(
            cfg.steps_per_month - 1, 1
        )
        # Numerical correction guarantees exact macro totals.
        fx += (target_fx - fx.sum(axis=1))[:, None] / cfg.steps_per_month
        eth += (target_eth - eth.sum(axis=1))[:, None] / cfg.steps_per_month
        fx_log[:, start:stop] = fx
        eth_log[:, start:stop] = eth

    lcu_usd = np.concatenate(
        [np.ones((n_paths, 1)), np.exp(np.cumsum(fx_log, axis=1))], axis=1
    )
    eth_usd = np.concatenate(
        [np.ones((n_paths, 1)), np.exp(np.cumsum(eth_log, axis=1))], axis=1
    )

    official_gap = np.empty((n_paths, n_steps), dtype=float)
    gap = np.full(n_paths, 0.01)
    for step in range(n_steps):
        month = min(step // cfg.steps_per_month, cfg.horizon_months - 1)
        target = np.clip(0.008 + 0.90 * np.maximum(macro[:, month, 0], 0.0), 0, 0.24)
        jump_pressure = 0.55 * np.maximum(-fx_log[:, step] - 0.006, 0.0)
        gap = np.clip(0.97 * gap + 0.03 * target + jump_pressure, 0.0, 0.30)
        official_gap[:, step] = gap

    attack_mask = np.zeros((n_paths, n_steps), dtype=bool)
    attack_size = np.zeros((n_paths, n_steps), dtype=float)
    selected = rng.random(n_paths) < attack_probability
    start_low = min(8, max(n_steps - 1, 0))
    start_high = max(start_low + 1, n_steps - 8)
    starts = rng.integers(start_low, start_high, size=n_paths)
    magnitudes = rng.uniform(0.15, 0.40, size=n_paths)
    for offset in range(4):
        indices = np.minimum(starts + offset, n_steps - 1)
        rows = np.where(selected)[0]
        attack_mask[rows, indices[rows]] = True
        attack_size[rows, indices[rows]] = magnitudes[rows]

    ref_lcu = rng.normal(0.0, 0.003, size=(n_paths, n_steps))
    ref_eth = rng.normal(0.0, 0.004, size=(n_paths, n_steps))
    return MarketPaths(
        lcu_usd=lcu_usd,
        eth_usd=eth_usd,
        official_gap=official_gap,
        attack_mask=attack_mask,
        attack_size=attack_size,
        reference_noise_lcu=ref_lcu,
        reference_noise_eth=ref_eth,
        fx_step_log_return=fx_log,
        eth_step_log_return=eth_log,
    )


def _oracle_observation(
    market: MarketPaths,
    step: int,
    dex_basis: np.ndarray,
    architecture: Architecture,
    official_gap_multiplier: float,
    attack_scale: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return LCU price, ETH price, source disagreement, and oracle age."""

    lag = max(int(round(architecture.official_latency_hours / 6)), 0)
    official_index = max(step + 1 - lag, 0)
    reference_index = max(step, 0)
    true_lcu = market.lcu_usd[:, step + 1]
    true_eth = market.eth_usd[:, step + 1]

    gap_index = max(step - lag, 0)
    official_lcu = market.lcu_usd[:, official_index] * np.exp(
        official_gap_multiplier * market.official_gap[:, gap_index]
    )
    official_eth = market.eth_usd[:, official_index]

    attack = attack_scale * market.attack_size[:, step]
    dex_lcu = true_lcu * np.exp(-dex_basis)
    dex_eth = true_eth * np.exp(attack)
    reference_lcu = market.lcu_usd[:, reference_index] * np.exp(
        market.reference_noise_lcu[:, step]
    )
    reference_eth = market.eth_usd[:, reference_index] * np.exp(
        market.reference_noise_eth[:, step]
    )

    if architecture.multi_oracle:
        lcu_sources = np.stack([official_lcu, dex_lcu, reference_lcu], axis=1)
        eth_sources = np.stack([official_eth, dex_eth, reference_eth], axis=1)
        lcu_hat = np.median(lcu_sources, axis=1)
        eth_hat = np.median(eth_sources, axis=1)
        ratio_sources = eth_sources / np.maximum(lcu_sources, 1e-15)
        disagreement = np.ptp(np.log(np.maximum(ratio_sources, 1e-15)), axis=1)
        age_hours = np.full(market.n_paths, 6.0)
    else:
        # The fragile benchmark combines an official FX source with a thin-DEX
        # collateral quote.  This mirrors the cross-domain composition risk of
        # using individually plausible but differently governed feeds.
        lcu_hat = official_lcu
        eth_hat = dex_eth
        ratio_pair = np.stack(
            [official_eth / np.maximum(official_lcu, 1e-15),
             dex_eth / np.maximum(dex_lcu, 1e-15)],
            axis=1,
        )
        disagreement = np.abs(np.diff(np.log(np.maximum(ratio_pair, 1e-15)), axis=1))[:, 0]
        age_hours = np.full(market.n_paths, float(architecture.official_latency_hours))
    return lcu_hat, eth_hat, disagreement, age_hours


def simulate_protocol(
    market: MarketPaths,
    architecture: Architecture,
    currency: str,
    config: SimulationConfig | None = None,
    official_gap_multiplier: float = 1.0,
    attack_scale: float = 1.0,
    keep_paths: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Simulate lending, liquidations, DEX pressure, and adaptive controls."""

    cfg = config or SimulationConfig()
    if market.n_steps != cfg.n_steps:
        raise ValueError("market path length and configuration do not agree")
    if official_gap_multiplier < 0 or attack_scale < 0:
        raise ValueError("stress multipliers must be non-negative")

    n_paths = market.n_paths
    n_tranches = 8
    weights = np.array([0.08, 0.12, 0.17, 0.19, 0.17, 0.13, 0.09, 0.05])
    opening_cr = np.array([1.53, 1.60, 1.69, 1.80, 1.94, 2.12, 2.36, 2.70])
    debt_units = np.repeat((cfg.initial_debt * weights)[None, :], n_paths, axis=0)
    collateral_units = debt_units * opening_cr[None, :]

    rate = np.full(n_paths, cfg.initial_rate)
    ceiling = np.full(n_paths, cfg.initial_debt_ceiling)
    liquidation_ratio = np.full(n_paths, cfg.initial_liquidation_ratio)
    dex_basis = np.zeros(n_paths)
    ewma_variance = np.full(n_paths, 0.01**2)
    breaker_cooldown = np.zeros(n_paths, dtype=int)

    delay_steps = max(int(round(architecture.governance_delay_hours / cfg.step_hours)), 0)
    rate_queue = [rate.copy() for _ in range(delay_steps + 1)]
    ceiling_queue = [ceiling.copy() for _ in range(delay_steps + 1)]
    liquidation_queue = [liquidation_ratio.copy() for _ in range(delay_steps + 1)]

    cumulative_bad_debt = np.zeros(n_paths)
    cumulative_credit = np.zeros(n_paths)
    liquidation_events = np.zeros(n_paths)
    unnecessary_liquidations = np.zeros(n_paths)
    oracle_error_sum = np.zeros(n_paths)
    oracle_error_max = np.zeros(n_paths)
    disagreement_sum = np.zeros(n_paths)
    rate_sum = np.zeros(n_paths)
    ceiling_sum = np.zeros(n_paths)
    liq_ratio_sum = np.zeros(n_paths)
    basis_sum = np.zeros(n_paths)
    maximum_basis = np.zeros(n_paths)
    deep_depeg_steps = np.zeros(n_paths)
    paused_steps = np.zeros(n_paths)
    true_risk_steps = np.zeros(n_paths)
    true_positive_steps = np.zeros(n_paths)
    false_positive_steps = np.zeros(n_paths)
    parameter_turnover = np.zeros(n_paths)

    records: list[pd.DataFrame] = []
    sample_count = min(keep_paths, n_paths)
    step_rate = cfg.step_hours / (24.0 * 365.0)

    for step in range(cfg.n_steps):
        old_rate = rate.copy()
        old_ceiling = ceiling.copy()
        old_liquidation = liquidation_ratio.copy()

        lcu_hat, eth_hat, disagreement, oracle_age = _oracle_observation(
            market,
            step,
            dex_basis,
            architecture,
            official_gap_multiplier,
            attack_scale,
        )
        true_lcu = market.lcu_usd[:, step + 1]
        true_eth = market.eth_usd[:, step + 1]
        true_ratio = true_eth / np.maximum(true_lcu, 1e-15)
        oracle_ratio = eth_hat / np.maximum(lcu_hat, 1e-15)
        oracle_error = np.abs(np.log(np.maximum(oracle_ratio / true_ratio, 1e-15)))
        oracle_error_sum += oracle_error
        oracle_error_max = np.maximum(oracle_error_max, oracle_error)
        disagreement_sum += disagreement

        ratio_return = market.eth_step_log_return[:, step] - market.fx_step_log_return[:, step]
        ewma_variance = 0.92 * ewma_variance + 0.08 * ratio_return**2
        observed_volatility = np.sqrt(ewma_variance)

        debt_value_oracle = (debt_units * lcu_hat[:, None]).sum(axis=1)
        utilization = debt_value_oracle / np.maximum(ceiling, 1e-15)
        risk_score = np.clip(
            4.0 * observed_volatility
            + 3.2 * dex_basis
            + 1.8 * disagreement
            + 0.9 * np.maximum(utilization - 0.72, 0.0),
            0.0,
            1.0,
        )

        target_rate = np.clip(
            cfg.initial_rate + 0.90 * risk_score + 0.35 * np.maximum(utilization - 0.75, 0.0),
            0.04,
            cfg.max_rate,
        )
        target_ceiling = np.clip(
            cfg.initial_debt_ceiling * np.exp(-1.75 * risk_score),
            cfg.min_ceiling,
            cfg.initial_debt_ceiling,
        )
        target_liquidation = np.clip(
            cfg.initial_liquidation_ratio + 0.70 * risk_score,
            cfg.initial_liquidation_ratio,
            cfg.max_liquidation_ratio,
        )

        if architecture.adaptive:
            proposed_rate = rate + np.clip(target_rate - rate, -0.02, 0.05)
            proposed_ceiling = ceiling + np.clip(target_ceiling - ceiling, -0.05, 0.02)
            proposed_liquidation = liquidation_ratio + np.clip(
                target_liquidation - liquidation_ratio, -0.02, 0.035
            )
            if not architecture.control_rate:
                proposed_rate = np.full(n_paths, cfg.initial_rate)
            if not architecture.control_ceiling:
                proposed_ceiling = np.full(n_paths, cfg.initial_debt_ceiling)
            if not architecture.control_liquidation:
                proposed_liquidation = np.full(n_paths, cfg.initial_liquidation_ratio)

            rate_queue.append(proposed_rate)
            ceiling_queue.append(proposed_ceiling)
            liquidation_queue.append(proposed_liquidation)
            rate = rate_queue.pop(0)
            ceiling = ceiling_queue.pop(0)
            liquidation_ratio = liquidation_queue.pop(0)

        trigger = (
            (dex_basis > cfg.breaker_basis)
            | (disagreement > cfg.breaker_disagreement)
            | (observed_volatility > cfg.breaker_volatility)
            | (oracle_age > 36.0)
        )
        if architecture.circuit_breaker:
            breaker_cooldown = np.where(trigger, cfg.breaker_cooldown_steps, np.maximum(breaker_cooldown - 1, 0))
        else:
            breaker_cooldown.fill(0)
        paused = breaker_cooldown > 0

        true_risk = (
            (market.official_gap[:, step] * official_gap_multiplier > 0.06)
            | market.attack_mask[:, step]
            | (market.eth_step_log_return[:, step] < -0.07)
            | (dex_basis > 0.05)
        )
        true_risk_steps += true_risk
        true_positive_steps += paused & true_risk
        false_positive_steps += paused & ~true_risk
        paused_steps += paused

        # Interest accrues in LCU debt units.
        debt_units *= np.exp(rate[:, None] * step_rate)

        # Elastic draw demand is admitted only below the dynamic ceiling.
        demand = cfg.base_draw_per_step * np.exp(
            -cfg.borrower_rate_elasticity * np.maximum(rate - cfg.initial_rate, 0.0)
        )
        demand *= 1.0 + 7.0 * np.maximum(-market.fx_step_log_return[:, step], 0.0)
        # A manipulation episode attracts opportunistic borrowing.  A robust
        # oracle still admits the demand against correctly valued collateral;
        # a single manipulated collateral quote can under-collateralise it.
        demand += 0.025 * attack_scale * market.attack_size[:, step]
        demand = np.where(paused, 0.0, demand)
        gap_to_ceiling = np.maximum(ceiling - debt_value_oracle, 0.0)
        draw_usd_oracle = np.minimum(demand, gap_to_ceiling)
        draw_units_total = draw_usd_oracle / np.maximum(lcu_hat, 1e-15)
        draw_units = draw_units_total[:, None] * weights[None, :]
        target_cr = np.maximum(opening_cr[None, :], liquidation_ratio[:, None] + 0.10)
        added_collateral = (
            draw_units * lcu_hat[:, None] * target_cr / np.maximum(eth_hat[:, None], 1e-15)
        )
        debt_units += draw_units
        collateral_units += added_collateral
        true_credit = draw_units_total * true_lcu
        cumulative_credit += true_credit

        # New token sales and background conversion pressure move the DEX basis.
        background_flow = (
            0.0007
            + 0.055 * np.maximum(-market.fx_step_log_return[:, step], 0.0)
            + 0.004 * market.official_gap[:, step]
        )
        sell_flow = background_flow + true_credit
        arbitrage_capacity = 0.0015 * np.exp(
            -7.0 * market.official_gap[:, step] * official_gap_multiplier
        )
        net_pressure = np.maximum(sell_flow - arbitrage_capacity, 0.0)
        dex_basis = np.clip(
            cfg.basis_persistence * dex_basis
            + cfg.dex_impact * net_pressure / cfg.dex_depth,
            0.0,
            0.45,
        )

        # Liquidation uses the observed prices but settles at true contemporaneous value.
        debt_oracle_by_tranche = debt_units * lcu_hat[:, None]
        collateral_oracle_by_tranche = collateral_units * eth_hat[:, None]
        health = collateral_oracle_by_tranche / np.maximum(debt_oracle_by_tranche, 1e-15)
        active = debt_units > 0
        liquidate = active & (health < liquidation_ratio[:, None])
        debt_true = debt_units * true_lcu[:, None]
        collateral_true = collateral_units * true_eth[:, None]
        haircut = np.clip(
            0.045
            + 0.75 * observed_volatility
            + 0.65 * dex_basis,
            0.045,
            0.35,
        )
        recovery = collateral_true * (1.0 - haircut[:, None])
        bad_debt = np.where(liquidate, np.maximum(debt_true - recovery, 0.0), 0.0)
        cumulative_bad_debt += bad_debt.sum(axis=1)
        liquidation_events += liquidate.sum(axis=1)
        true_health = collateral_true / np.maximum(debt_true, 1e-15)
        unnecessary_liquidations += (liquidate & (true_health > liquidation_ratio[:, None] + 0.10)).sum(axis=1)
        debt_units = np.where(liquidate, 0.0, debt_units)
        collateral_units = np.where(liquidate, 0.0, collateral_units)

        rate_sum += rate
        ceiling_sum += ceiling
        liq_ratio_sum += liquidation_ratio
        basis_sum += dex_basis
        maximum_basis = np.maximum(maximum_basis, dex_basis)
        deep_depeg_steps += dex_basis > 0.05
        parameter_turnover += (
            np.abs(rate - old_rate)
            + np.abs(ceiling - old_ceiling)
            + np.abs(liquidation_ratio - old_liquidation)
        )

        if sample_count:
            records.append(
                pd.DataFrame(
                    {
                        "path_id": np.arange(sample_count),
                        "step": step,
                        "hour": (step + 1) * cfg.step_hours,
                        "currency": currency,
                        "architecture": architecture.name,
                        "lcu_usd": true_lcu[:sample_count],
                        "eth_usd": true_eth[:sample_count],
                        "oracle_ratio_error": np.log(
                            np.maximum(oracle_ratio[:sample_count] / true_ratio[:sample_count], 1e-15)
                        ),
                        "source_disagreement": disagreement[:sample_count],
                        "dex_discount": dex_basis[:sample_count],
                        "annual_rate": rate[:sample_count],
                        "debt_ceiling": ceiling[:sample_count],
                        "liquidation_ratio": liquidation_ratio[:sample_count],
                        "paused": paused[:sample_count].astype(int),
                        "bad_debt_cumulative": cumulative_bad_debt[:sample_count],
                        "credit_cumulative": cumulative_credit[:sample_count],
                    }
                )
            )

    final_debt_true = (debt_units * market.lcu_usd[:, -1, None]).sum(axis=1)
    final_collateral_true = (collateral_units * market.eth_usd[:, -1, None]).sum(axis=1)
    denominator = float(cfg.n_steps)
    results = pd.DataFrame(
        {
            "currency": currency,
            "architecture": architecture.name,
            "path_id": np.arange(n_paths),
            "bad_debt": cumulative_bad_debt,
            "bad_debt_share_initial_debt": cumulative_bad_debt / cfg.initial_debt,
            "bad_debt_event": (cumulative_bad_debt > 0.001).astype(int),
            "credit_issued": cumulative_credit,
            "liquidation_events": liquidation_events,
            "unnecessary_liquidations": unnecessary_liquidations,
            "mean_abs_oracle_error": oracle_error_sum / denominator,
            "maximum_abs_oracle_error": oracle_error_max,
            "mean_source_disagreement": disagreement_sum / denominator,
            "maximum_dex_discount": maximum_basis,
            "deep_depeg_share": deep_depeg_steps / denominator,
            # A 10% discount is treated as a severe depeg/collapse event;
            # ``deep_depeg_share`` separately records time beyond 5%.
            "deep_depeg_event": (maximum_basis > 0.10).astype(int),
            "mean_dex_discount": basis_sum / denominator,
            "mean_annual_rate": rate_sum / denominator,
            "mean_debt_ceiling": ceiling_sum / denominator,
            "mean_liquidation_ratio": liq_ratio_sum / denominator,
            "pause_share": paused_steps / denominator,
            "breaker_true_positive_rate": true_positive_steps / np.maximum(true_risk_steps, 1.0),
            "breaker_false_positive_share": false_positive_steps / denominator,
            "parameter_turnover": parameter_turnover,
            "final_debt_value": final_debt_true,
            "final_collateral_value": final_collateral_true,
        }
    )
    monthly = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    return results, monthly


def summarise_results(results: pd.DataFrame) -> dict[str, object]:
    """Stable manuscript-facing summary of a path distribution."""

    return {
        "currency": results["currency"].iloc[0],
        "architecture": results["architecture"].iloc[0],
        "paths": int(len(results)),
        "bad_debt_probability": float(results["bad_debt_event"].mean()),
        "mean_bad_debt_share": float(results["bad_debt_share_initial_debt"].mean()),
        "p95_bad_debt_share": float(results["bad_debt_share_initial_debt"].quantile(0.95)),
        "deep_depeg_probability": float(results["deep_depeg_event"].mean()),
        "mean_maximum_dex_discount": float(results["maximum_dex_discount"].mean()),
        "mean_credit_issued": float(results["credit_issued"].mean()),
        "mean_oracle_error": float(results["mean_abs_oracle_error"].mean()),
        "p95_maximum_oracle_error": float(results["maximum_abs_oracle_error"].quantile(0.95)),
        "mean_liquidation_events": float(results["liquidation_events"].mean()),
        "mean_unnecessary_liquidations": float(results["unnecessary_liquidations"].mean()),
        "mean_rate": float(results["mean_annual_rate"].mean()),
        "mean_ceiling": float(results["mean_debt_ceiling"].mean()),
        "mean_liquidation_ratio": float(results["mean_liquidation_ratio"].mean()),
        "mean_pause_share": float(results["pause_share"].mean()),
        "mean_breaker_tpr": float(results["breaker_true_positive_rate"].mean()),
        "mean_breaker_false_positive_share": float(
            results["breaker_false_positive_share"].mean()
        ),
        "mean_parameter_turnover": float(results["parameter_turnover"].mean()),
    }


def with_architecture(architecture: Architecture, **changes: object) -> Architecture:
    """Typed convenience wrapper used by robustness experiments."""

    return replace(architecture, **changes)
