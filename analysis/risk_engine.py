"""Pure, shared mathematics for the simulated and shadow risk engines.

Keeping these functions free of I/O makes the controller equations auditable and
ensures that replay/shadow recommendations use the same mapping as the paper's
simulation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RiskEngineConfig:
    """Controller constants at one risk-update interval."""

    initial_rate: float = 0.08
    initial_debt_ceiling: float = 1.0
    initial_liquidation_ratio: float = 1.50
    max_rate: float = 1.50
    min_ceiling: float = 0.20
    max_liquidation_ratio: float = 2.20
    breaker_basis: float = 0.065
    breaker_disagreement: float = 0.140
    breaker_volatility: float = 0.100
    ewma_memory: float = 0.92
    volatility_weight: float = 4.0
    basis_weight: float = 3.2
    disagreement_weight: float = 1.8
    utilization_weight: float = 0.9
    rate_risk_gain: float = 0.90
    rate_utilization_gain: float = 0.35
    ceiling_risk_gain: float = 1.75
    liquidation_risk_gain: float = 0.70
    rate_step_down: float = 0.02
    rate_step_up: float = 0.05
    ceiling_step_down: float = 0.05
    ceiling_step_up: float = 0.02
    liquidation_step_down: float = 0.02
    liquidation_step_up: float = 0.035


def update_ewma_variance(
    previous_variance: np.ndarray | float,
    ratio_log_return: np.ndarray | float,
    memory: float = 0.92,
) -> np.ndarray:
    """Return ``memory * v[t] + (1-memory) * q[t]^2``."""

    if not 0.0 <= memory < 1.0:
        raise ValueError("EWMA memory must lie in [0, 1)")

    return memory * np.asarray(previous_variance, dtype=float) + (
        1.0 - memory
    ) * np.square(np.asarray(ratio_log_return, dtype=float))


def compute_risk_score(
    observed_volatility: np.ndarray | float,
    dex_basis: np.ndarray | float,
    disagreement: np.ndarray | float,
    utilization: np.ndarray | float,
    config: RiskEngineConfig | None = None,
) -> np.ndarray:
    """Map observable risk features into the bounded score in Section 5."""

    cfg = config or RiskEngineConfig()

    return np.clip(
        cfg.volatility_weight * np.asarray(observed_volatility, dtype=float)
        + cfg.basis_weight * np.asarray(dex_basis, dtype=float)
        + cfg.disagreement_weight * np.asarray(disagreement, dtype=float)
        + cfg.utilization_weight
        * np.maximum(np.asarray(utilization, dtype=float) - 0.72, 0.0),
        0.0,
        1.0,
    )


def compute_targets(
    risk_score: np.ndarray | float,
    utilization: np.ndarray | float,
    config: RiskEngineConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return unconstrained-by-speed targets for rate, ceiling, and LR."""

    risk = np.asarray(risk_score, dtype=float)
    util = np.asarray(utilization, dtype=float)
    target_rate = np.clip(
        config.initial_rate
        + config.rate_risk_gain * risk
        + config.rate_utilization_gain * np.maximum(util - 0.75, 0.0),
        0.04,
        config.max_rate,
    )
    target_ceiling = np.clip(
        config.initial_debt_ceiling * np.exp(-config.ceiling_risk_gain * risk),
        config.min_ceiling,
        config.initial_debt_ceiling,
    )
    target_liquidation = np.clip(
        config.initial_liquidation_ratio + config.liquidation_risk_gain * risk,
        config.initial_liquidation_ratio,
        config.max_liquidation_ratio,
    )
    return target_rate, target_ceiling, target_liquidation


def rate_limited_update(
    rate: np.ndarray | float,
    ceiling: np.ndarray | float,
    liquidation_ratio: np.ndarray | float,
    targets: tuple[np.ndarray | float, np.ndarray | float, np.ndarray | float],
    config: RiskEngineConfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply the paper's asymmetric per-step parameter movement limits."""

    cfg = config or RiskEngineConfig()
    target_rate, target_ceiling, target_liquidation = targets
    next_rate = np.asarray(rate, dtype=float) + np.clip(
        np.asarray(target_rate, dtype=float) - np.asarray(rate, dtype=float),
        -cfg.rate_step_down,
        cfg.rate_step_up,
    )
    next_ceiling = np.asarray(ceiling, dtype=float) + np.clip(
        np.asarray(target_ceiling, dtype=float) - np.asarray(ceiling, dtype=float),
        -cfg.ceiling_step_down,
        cfg.ceiling_step_up,
    )
    next_liquidation = np.asarray(liquidation_ratio, dtype=float) + np.clip(
        np.asarray(target_liquidation, dtype=float)
        - np.asarray(liquidation_ratio, dtype=float),
        -cfg.liquidation_step_down,
        cfg.liquidation_step_up,
    )
    return next_rate, next_ceiling, next_liquidation


def breaker_trigger(
    dex_basis: np.ndarray | float,
    disagreement: np.ndarray | float,
    observed_volatility: np.ndarray | float,
    oracle_age_hours: np.ndarray | float,
    config: RiskEngineConfig,
) -> np.ndarray:
    """Return the paper's circuit-breaker predicate."""

    return (
        (np.asarray(dex_basis, dtype=float) > config.breaker_basis)
        | (np.asarray(disagreement, dtype=float) > config.breaker_disagreement)
        | (np.asarray(observed_volatility, dtype=float) > config.breaker_volatility)
        | (np.asarray(oracle_age_hours, dtype=float) > 36.0)
    )
