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


def update_ewma_variance(
    previous_variance: np.ndarray | float,
    ratio_log_return: np.ndarray | float,
) -> np.ndarray:
    """Return ``0.92 * v[t] + 0.08 * q[t]^2``."""

    return 0.92 * np.asarray(previous_variance, dtype=float) + 0.08 * np.square(
        np.asarray(ratio_log_return, dtype=float)
    )


def compute_risk_score(
    observed_volatility: np.ndarray | float,
    dex_basis: np.ndarray | float,
    disagreement: np.ndarray | float,
    utilization: np.ndarray | float,
) -> np.ndarray:
    """Map observable risk features into the bounded score in Section 5."""

    return np.clip(
        4.0 * np.asarray(observed_volatility, dtype=float)
        + 3.2 * np.asarray(dex_basis, dtype=float)
        + 1.8 * np.asarray(disagreement, dtype=float)
        + 0.9 * np.maximum(np.asarray(utilization, dtype=float) - 0.72, 0.0),
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
        config.initial_rate + 0.90 * risk + 0.35 * np.maximum(util - 0.75, 0.0),
        0.04,
        config.max_rate,
    )
    target_ceiling = np.clip(
        config.initial_debt_ceiling * np.exp(-1.75 * risk),
        config.min_ceiling,
        config.initial_debt_ceiling,
    )
    target_liquidation = np.clip(
        config.initial_liquidation_ratio + 0.70 * risk,
        config.initial_liquidation_ratio,
        config.max_liquidation_ratio,
    )
    return target_rate, target_ceiling, target_liquidation


def rate_limited_update(
    rate: np.ndarray | float,
    ceiling: np.ndarray | float,
    liquidation_ratio: np.ndarray | float,
    targets: tuple[np.ndarray | float, np.ndarray | float, np.ndarray | float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply the paper's asymmetric per-step parameter movement limits."""

    target_rate, target_ceiling, target_liquidation = targets
    next_rate = np.asarray(rate, dtype=float) + np.clip(
        np.asarray(target_rate, dtype=float) - np.asarray(rate, dtype=float),
        -0.02,
        0.05,
    )
    next_ceiling = np.asarray(ceiling, dtype=float) + np.clip(
        np.asarray(target_ceiling, dtype=float) - np.asarray(ceiling, dtype=float),
        -0.05,
        0.02,
    )
    next_liquidation = np.asarray(liquidation_ratio, dtype=float) + np.clip(
        np.asarray(target_liquidation, dtype=float)
        - np.asarray(liquidation_ratio, dtype=float),
        -0.02,
        0.035,
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
