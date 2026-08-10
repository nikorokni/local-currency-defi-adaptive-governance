#!/usr/bin/env python3
"""Reproduce simulations, sensitivity analyses, figures, tables, and anchors."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyBboxPatch

from model import (
    Architecture,
    MAIN_ARCHITECTURES,
    SimulationConfig,
    build_market_paths,
    historical_joint_windows,
    moving_block_bootstrap_joint,
    simulate_protocol,
    summarise_results,
)


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"
TABLES = ROOT / "tables"
DOCS = ROOT / "documentation"
SEED = 20260810
N_PATHS = 6_000
SENSITIVITY_PATHS = 1_200
BLOCK_LENGTH = 2
CONFIG = SimulationConfig()

ARCH_SHORT = {
    "Static single oracle": "Static single",
    "Delayed DAO": "Delayed DAO",
    "Adaptive multi-oracle": "Adaptive multi",
    "Adaptive multi + breaker": "Adaptive + breaker",
}
COLORS = {
    "Static single oracle": "#A23B72",
    "Delayed DAO": "#F18F01",
    "Adaptive multi-oracle": "#2E86AB",
    "Adaptive multi + breaker": "#2A9D8F",
}


def ensure_dirs() -> None:
    for path in [RESULTS, FIGURES, TABLES, DOCS]:
        path.mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_panel() -> pd.DataFrame:
    path = DATA / "processed" / "joint_monthly_market_panel.csv"
    panel = pd.read_csv(path, parse_dates=["month"])
    required = {
        "month",
        "ars_per_usd",
        "try_per_usd",
        "eth_usd",
        "ars_depreciation",
        "try_depreciation",
        "eth_return",
    }
    if not required.issubset(panel.columns):
        raise ValueError(f"Missing columns: {sorted(required - set(panel.columns))}")
    if len(panel) != 43 or panel[list(required - {"month"})].isna().sum().max() > 1:
        raise ValueError("Expected the common 43-month research panel")
    if panel[["ars_depreciation", "try_depreciation", "eth_return"]].dropna().shape[0] != 42:
        raise ValueError("Expected 42 complete joint return observations")
    return panel


def market_for_currency(
    panel: pd.DataFrame,
    currency: str,
    n_paths: int,
    seed_offset: int,
    historical: bool = False,
) -> tuple[np.ndarray, object]:
    fx_column = "ars_depreciation" if currency == "ARS" else "try_depreciation"
    joint = panel[[fx_column, "eth_return"]].dropna().to_numpy()
    if historical:
        macro = historical_joint_windows(joint, CONFIG.horizon_months)
    else:
        macro = moving_block_bootstrap_joint(
            joint,
            n_paths=n_paths,
            horizon=CONFIG.horizon_months,
            block_length=BLOCK_LENGTH,
            seed=SEED + seed_offset,
        )
    # Put the largest joint FX/collateral stress first so path zero is an
    # informative, deterministic representative crisis path.
    stress = macro[:, :, 0].sum(axis=1) - macro[:, :, 1].sum(axis=1)
    macro = macro[np.argsort(stress)[::-1]]
    market = build_market_paths(
        macro,
        seed=SEED + 100 + seed_offset,
        config=CONFIG,
        attack_probability=0.22,
    )
    return macro, market


def distribution_record(frame: pd.DataFrame) -> dict[str, object]:
    record: dict[str, object] = {
        "currency": frame["currency"].iloc[0],
        "architecture": frame["architecture"].iloc[0],
    }
    metrics = [
        "bad_debt_share_initial_debt",
        "credit_issued",
        "maximum_abs_oracle_error",
        "maximum_dex_discount",
        "mean_annual_rate",
        "mean_debt_ceiling",
        "pause_share",
    ]
    for metric in metrics:
        for label, quantile in [("p05", 0.05), ("p50", 0.50), ("p95", 0.95), ("p99", 0.99)]:
            record[f"{metric}_{label}"] = float(frame[metric].quantile(quantile))
    return record


def run_main(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    summaries: list[dict[str, object]] = []
    distributions: list[dict[str, object]] = []
    samples: list[pd.DataFrame] = []
    markets: dict[str, object] = {}

    for currency, seed_offset in [("ARS", 0), ("TRY", 10)]:
        _, market = market_for_currency(panel, currency, N_PATHS, seed_offset)
        markets[currency] = market
        for architecture in MAIN_ARCHITECTURES:
            results, monthly = simulate_protocol(
                market,
                architecture,
                currency,
                CONFIG,
                keep_paths=3,
            )
            summaries.append(summarise_results(results))
            distributions.append(distribution_record(results))
            samples.append(monthly)

    summary = pd.DataFrame(summaries)
    distribution = pd.DataFrame(distributions)
    representative = pd.concat(samples, ignore_index=True)
    summary.to_csv(RESULTS / "main_scenario_summary.csv", index=False, float_format="%.9g")
    distribution.to_csv(
        RESULTS / "main_distribution_quantiles.csv", index=False, float_format="%.9g"
    )
    representative.to_csv(
        RESULTS / "representative_six_hour_paths.csv", index=False, float_format="%.9g"
    )
    return summary, distribution, representative, markets


def run_historical(panel: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for currency, seed_offset in [("ARS", 30), ("TRY", 40)]:
        _, market = market_for_currency(
            panel, currency, n_paths=1, seed_offset=seed_offset, historical=True
        )
        for architecture in MAIN_ARCHITECTURES:
            results, _ = simulate_protocol(
                market, architecture, currency, CONFIG, keep_paths=0
            )
            record = summarise_results(results)
            record["distribution"] = "39 realised rolling four-month windows"
            records.append(record)
    historical = pd.DataFrame(records)
    historical.to_csv(
        RESULTS / "historical_replay_summary.csv", index=False, float_format="%.9g"
    )
    return historical


def run_latency_basis_grid(panel: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    latencies = [0, 6, 12, 24, 48]
    gap_multipliers = [0.0, 0.5, 1.0, 1.5, 2.0]
    benchmark = MAIN_ARCHITECTURES[0]
    for currency, seed_offset in [("ARS", 50), ("TRY", 60)]:
        _, market = market_for_currency(
            panel, currency, SENSITIVITY_PATHS, seed_offset
        )
        for latency in latencies:
            architecture = replace(benchmark, official_latency_hours=latency)
            for multiplier in gap_multipliers:
                results, _ = simulate_protocol(
                    market,
                    architecture,
                    currency,
                    CONFIG,
                    official_gap_multiplier=multiplier,
                    keep_paths=0,
                )
                records.append(
                    {
                        "currency": currency,
                        "latency_hours": latency,
                        "official_gap_multiplier": multiplier,
                        "bad_debt_probability": results["bad_debt_event"].mean(),
                        "severe_depeg_probability": results["deep_depeg_event"].mean(),
                        "mean_oracle_error": results["mean_abs_oracle_error"].mean(),
                        "p95_maximum_oracle_error": results[
                            "maximum_abs_oracle_error"
                        ].quantile(0.95),
                        "mean_unnecessary_liquidations": results[
                            "unnecessary_liquidations"
                        ].mean(),
                    }
                )
    frame = pd.DataFrame(records)
    frame.to_csv(RESULTS / "latency_basis_grid.csv", index=False, float_format="%.9g")
    return frame


def run_attack_robustness(panel: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    attack_scales = [0.0, 0.5, 1.0, 1.5, 2.0]
    selected = [MAIN_ARCHITECTURES[0], MAIN_ARCHITECTURES[-1]]
    for currency, seed_offset in [("ARS", 70), ("TRY", 80)]:
        _, market = market_for_currency(
            panel, currency, SENSITIVITY_PATHS, seed_offset
        )
        for architecture in selected:
            for scale in attack_scales:
                results, _ = simulate_protocol(
                    market,
                    architecture,
                    currency,
                    CONFIG,
                    attack_scale=scale,
                    keep_paths=0,
                )
                records.append(
                    {
                        "currency": currency,
                        "architecture": architecture.name,
                        "attack_scale": scale,
                        "bad_debt_probability": results["bad_debt_event"].mean(),
                        "mean_bad_debt_share": results[
                            "bad_debt_share_initial_debt"
                        ].mean(),
                        "p95_maximum_oracle_error": results[
                            "maximum_abs_oracle_error"
                        ].quantile(0.95),
                        "mean_credit_issued": results["credit_issued"].mean(),
                    }
                )
    frame = pd.DataFrame(records)
    frame.to_csv(RESULTS / "attack_robustness.csv", index=False, float_format="%.9g")
    return frame


def run_governance_delay(panel: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    delays = [0, 6, 12, 24, 48, 72]
    base = replace(MAIN_ARCHITECTURES[2], circuit_breaker=False)
    for currency, seed_offset in [("ARS", 90), ("TRY", 100)]:
        _, market = market_for_currency(
            panel, currency, SENSITIVITY_PATHS, seed_offset
        )
        for delay in delays:
            architecture = replace(
                base,
                name=f"Adaptive multi ({delay}h delay)",
                governance_delay_hours=delay,
            )
            results, _ = simulate_protocol(
                market, architecture, currency, CONFIG, keep_paths=0
            )
            records.append(
                {
                    "currency": currency,
                    "delay_hours": delay,
                    "bad_debt_probability": results["bad_debt_event"].mean(),
                    "severe_depeg_probability": results[
                        "deep_depeg_event"
                    ].mean(),
                    "mean_credit_issued": results["credit_issued"].mean(),
                    "mean_rate": results["mean_annual_rate"].mean(),
                    "mean_ceiling": results["mean_debt_ceiling"].mean(),
                    "mean_parameter_turnover": results["parameter_turnover"].mean(),
                }
            )
    frame = pd.DataFrame(records)
    frame.to_csv(RESULTS / "governance_delay.csv", index=False, float_format="%.9g")
    return frame


def run_controller_ablation(panel: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    base = MAIN_ARCHITECTURES[-1]
    designs = [
        ("Rate only", dict(control_rate=True, control_ceiling=False, control_liquidation=False, circuit_breaker=False)),
        ("Ceiling only", dict(control_rate=False, control_ceiling=True, control_liquidation=False, circuit_breaker=False)),
        ("Liquidation only", dict(control_rate=False, control_ceiling=False, control_liquidation=True, circuit_breaker=False)),
        ("All controls", dict(control_rate=True, control_ceiling=True, control_liquidation=True, circuit_breaker=False)),
        ("All + breaker", dict(control_rate=True, control_ceiling=True, control_liquidation=True, circuit_breaker=True)),
    ]
    for currency, seed_offset in [("ARS", 110), ("TRY", 120)]:
        _, market = market_for_currency(
            panel, currency, SENSITIVITY_PATHS, seed_offset
        )
        for label, changes in designs:
            architecture = replace(base, name=label, **changes)
            results, _ = simulate_protocol(
                market, architecture, currency, CONFIG, keep_paths=0
            )
            records.append(
                {
                    "currency": currency,
                    "design": label,
                    "bad_debt_probability": results["bad_debt_event"].mean(),
                    "severe_depeg_probability": results[
                        "deep_depeg_event"
                    ].mean(),
                    "mean_credit_issued": results["credit_issued"].mean(),
                    "mean_pause_share": results["pause_share"].mean(),
                    "mean_rate": results["mean_annual_rate"].mean(),
                    "mean_ceiling": results["mean_debt_ceiling"].mean(),
                }
            )
    frame = pd.DataFrame(records)
    frame.to_csv(RESULTS / "controller_ablation.csv", index=False, float_format="%.9g")
    return frame


def latex_escape(value: object) -> str:
    text = str(value)
    if "\\" in text or "$" in text:
        return text
    return (
        text.replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
    )


def write_tabular(path: Path, rows: list[list[object]], columns: str) -> None:
    lines = [rf"\begin{{tabular}}{{{columns}}}", r"\toprule"]
    for index, row in enumerate(rows):
        lines.append(" & ".join(latex_escape(value) for value in row) + r" \\")
        if index == 0:
            lines.append(r"\midrule")
    lines.extend([r"\bottomrule", r"\end{tabular}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def make_tables(
    panel: pd.DataFrame,
    main: pd.DataFrame,
    latency: pd.DataFrame,
    attack: pd.DataFrame,
    delay: pd.DataFrame,
    ablation: pd.DataFrame,
) -> None:
    clean = panel.dropna()
    data_rows = [["Series", "Observations", "Mean", "SD", "Minimum", "Maximum"]]
    for label, column, scale in [
        ("ARS depreciation", "ars_depreciation", 100),
        ("TRY depreciation", "try_depreciation", 100),
        ("ETH return", "eth_return", 100),
    ]:
        values = clean[column] * scale
        data_rows.append(
            [
                label,
                len(values),
                f"{values.mean():.2f}\\%",
                f"{values.std():.2f}\\%",
                f"{values.min():.2f}\\%",
                f"{values.max():.2f}\\%",
            ]
        )
    write_tabular(TABLES / "table1_data_summary.tex", data_rows, "lrrrrr")

    architecture_rows = [["Architecture", "Price aggregation", "Parameter action", "Breaker"]]
    architecture_rows.extend(
        [
            ["Static single", "Official FX + DEX collateral", "Fixed", "No"],
            ["Delayed DAO", "Three-source median", "48-hour delay", "No"],
            ["Adaptive multi", "Three-source median", "Six-hour controller", "No"],
            ["Adaptive + breaker", "Three-source median", "Six-hour controller", "Four-step cooldown"],
        ]
    )
    write_tabular(TABLES / "table2_architectures.tex", architecture_rows, "p{3.2cm}p{4.0cm}p{3.2cm}p{2.6cm}")

    main_rows = [["Currency", "Architecture", "Bad debt", "Severe depeg", "Credit", "Oracle MAE", "Pause"]]
    for _, row in main.iterrows():
        main_rows.append(
            [
                row["currency"],
                ARCH_SHORT[row["architecture"]],
                f"{100 * row['bad_debt_probability']:.1f}\\%",
                f"{100 * row['deep_depeg_probability']:.1f}\\%",
                f"{row['mean_credit_issued']:.3f}",
                f"{100 * row['mean_oracle_error']:.2f}\\%",
                f"{100 * row['mean_pause_share']:.1f}\\%",
            ]
        )
    write_tabular(TABLES / "table3_main_results.tex", main_rows, "llrrrrr")

    oracle_rows = [["Currency", "Architecture", "P95 max error", "Liquidations", "Unnecessary", "Mean rate", "Mean ceiling"]]
    for _, row in main.iterrows():
        oracle_rows.append(
            [
                row["currency"],
                ARCH_SHORT[row["architecture"]],
                f"{100 * row['p95_maximum_oracle_error']:.2f}\\%",
                f"{row['mean_liquidation_events']:.2f}",
                f"{row['mean_unnecessary_liquidations']:.2f}",
                f"{100 * row['mean_rate']:.1f}\\%",
                f"{row['mean_ceiling']:.3f}",
            ]
        )
    write_tabular(TABLES / "table4_oracle_control.tex", oracle_rows, "llrrrrr")

    delay_rows = [["Delay", "ARS bad debt", "TRY bad debt", "ARS depeg", "TRY depeg", "Mean credit"]]
    for delay_hours in sorted(delay["delay_hours"].unique()):
        subset = delay[delay["delay_hours"] == delay_hours].set_index("currency")
        delay_rows.append(
            [
                f"{delay_hours} h",
                f"{100 * subset.loc['ARS', 'bad_debt_probability']:.1f}\\%",
                f"{100 * subset.loc['TRY', 'bad_debt_probability']:.1f}\\%",
                f"{100 * subset.loc['ARS', 'severe_depeg_probability']:.1f}\\%",
                f"{100 * subset.loc['TRY', 'severe_depeg_probability']:.1f}\\%",
                f"{subset['mean_credit_issued'].mean():.3f}",
            ]
        )
    write_tabular(TABLES / "table5_governance_delay.tex", delay_rows, "lrrrrr")

    ablation_rows = [["Design", "Bad debt", "Severe depeg", "Credit", "Pause", "Mean ceiling"]]
    means = ablation.groupby("design", sort=False).mean(numeric_only=True)
    for design in ["Rate only", "Ceiling only", "Liquidation only", "All controls", "All + breaker"]:
        row = means.loc[design]
        ablation_rows.append(
            [
                design,
                f"{100 * row['bad_debt_probability']:.1f}\\%",
                f"{100 * row['severe_depeg_probability']:.1f}\\%",
                f"{row['mean_credit_issued']:.3f}",
                f"{100 * row['mean_pause_share']:.1f}\\%",
                f"{row['mean_ceiling']:.3f}",
            ]
        )
    write_tabular(TABLES / "table6_ablation.tex", ablation_rows, "lrrrrr")

    # Machine-readable scalar summaries used in the robustness text.
    latency.groupby(["latency_hours", "official_gap_multiplier"], as_index=False).mean(
        numeric_only=True
    ).to_csv(RESULTS / "latency_basis_grid_pooled.csv", index=False, float_format="%.9g")
    attack.groupby(["architecture", "attack_scale"], as_index=False).mean(
        numeric_only=True
    ).to_csv(RESULTS / "attack_robustness_pooled.csv", index=False, float_format="%.9g")


def save_figure(fig: plt.Figure, filename: str) -> None:
    target = FIGURES / filename
    temporary = target.with_suffix(".tmp.png")
    fig.savefig(
        temporary,
        format="png",
        dpi=300,
        bbox_inches="tight",
        facecolor="white",
    )
    plt.close(fig)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def figure_architecture() -> None:
    fig, ax = plt.subplots(figsize=(11.5, 6.2))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 7)
    ax.axis("off")

    def box(x: float, y: float, width: float, height: float, title: str, body: str, color: str) -> None:
        patch = FancyBboxPatch(
            (x, y), width, height,
            boxstyle="round,pad=0.03,rounding_size=0.12",
            linewidth=1.6, edgecolor=color, facecolor=color + "18",
        )
        ax.add_patch(patch)
        ax.text(x + 0.18, y + height - 0.32, title, fontsize=11, fontweight="bold", color=color, va="top")
        ax.text(x + 0.18, y + height - 0.78, body, fontsize=9.1, color="#263238", va="top", linespacing=1.35)

    box(0.3, 4.5, 2.8, 1.65, "Three price domains", "Official FX\nDEX execution price\nIndependent reference", "#2E86AB")
    box(4.0, 4.5, 3.1, 1.65, "Robust oracle layer", "Freshness checks\nLog-median aggregation\nDisagreement signal", "#6A4C93")
    box(8.0, 4.5, 3.4, 1.65, "Risk-state estimator", "EWMA volatility\nDEX basis and utilisation\nComposite risk score", "#A23B72")
    box(1.0, 1.2, 3.2, 1.75, "Bounded controller", "Borrow rate\nDebt ceiling\nLiquidation ratio", "#F18F01")
    box(5.0, 1.2, 2.7, 1.75, "Circuit breaker", "Pause new draws\nFour-step cooldown\nContinue repayments", "#D1495B")
    box(8.5, 1.2, 2.8, 1.75, "Protocol state", "Credit issuance\nLiquidations / bad debt\nSecondary-market basis", "#2A9D8F")
    arrows = [
        ((3.1, 5.33), (4.0, 5.33)), ((7.1, 5.33), (8.0, 5.33)),
        ((9.7, 4.5), (3.1, 2.95)), ((9.7, 4.5), (6.35, 2.95)),
        ((4.2, 2.08), (5.0, 2.08)), ((7.7, 2.08), (8.5, 2.08)),
        ((8.5, 1.45), (4.2, 1.45)),
    ]
    for start, end in arrows:
        ax.annotate("", xy=end, xytext=start, arrowprops=dict(arrowstyle="->", lw=1.5, color="#455A64"))
    ax.text(6, 6.65, "Adaptive multi-oracle risk architecture", ha="center", fontsize=15, fontweight="bold")
    ax.text(6, 0.35, "Controls are rate-limited; the breaker blocks new borrowing but does not block repayment or collateral top-ups.", ha="center", fontsize=9.5, color="#455A64")
    save_figure(fig, "figure1_adaptive_architecture.png")


def figure_data(panel: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 7.2))
    axes[0, 0].plot(panel["month"], panel["ars_per_usd"], color="#A23B72", lw=2.2)
    axes[0, 0].set_title("Argentina: local currency per USD")
    axes[0, 1].plot(panel["month"], panel["try_per_usd"], color="#F18F01", lw=2.2)
    axes[0, 1].set_title("Türkiye: local currency per USD")
    axes[1, 0].plot(panel["month"], panel["eth_usd"], color="#2E86AB", lw=2.2)
    axes[1, 0].set_title("ETH collateral price (USD)")
    clean = panel.dropna()
    axes[1, 1].hist(100 * clean["ars_depreciation"], bins=12, alpha=0.65, color="#A23B72", label="ARS")
    axes[1, 1].hist(100 * clean["try_depreciation"], bins=12, alpha=0.60, color="#F18F01", label="TRY")
    axes[1, 1].set_title("Monthly depreciation distribution")
    axes[1, 1].set_xlabel("Per cent")
    axes[1, 1].legend(frameon=False)
    for ax in axes.flat:
        ax.grid(alpha=0.22)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Empirical calibration panel, January 2020--July 2023", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save_figure(fig, "figure2_empirical_calibration.png")


def figure_main(main: pd.DataFrame) -> None:
    metrics = [
        ("bad_debt_probability", "Bad-debt probability", 100),
        ("deep_depeg_probability", "Severe-depeg probability", 100),
        ("mean_credit_issued", "Credit issued / initial ceiling", 1),
        ("mean_oracle_error", "Mean absolute oracle error", 100),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.6))
    architectures = [a.name for a in MAIN_ARCHITECTURES]
    x = np.arange(len(architectures))
    width = 0.34
    for ax, (metric, title, scale) in zip(axes.flat, metrics):
        for offset, currency in [(-width / 2, "ARS"), (width / 2, "TRY")]:
            values = main[main["currency"] == currency].set_index("architecture").loc[architectures, metric] * scale
            ax.bar(x + offset, values, width, label=currency, color="#2E86AB" if currency == "ARS" else "#F18F01", alpha=0.88)
        ax.set_title(title)
        ax.set_xticks(x, [ARCH_SHORT[a] for a in architectures], rotation=18, ha="right")
        ax.grid(axis="y", alpha=0.22)
        ax.spines[["top", "right"]].set_visible(False)
        if scale == 100:
            ax.set_ylabel("Per cent")
    axes[0, 0].legend(frameon=False)
    fig.suptitle(f"Main counterfactual results ({N_PATHS:,} paths per currency and architecture)", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save_figure(fig, "figure3_main_outcomes.png")


def figure_latency_heatmap(latency: pd.DataFrame) -> None:
    pooled = latency.groupby(["latency_hours", "official_gap_multiplier"], as_index=False).mean(numeric_only=True)
    metrics = [
        ("mean_unnecessary_liquidations", "Mean unnecessary liquidations", 1, "Events per path"),
        ("mean_oracle_error", "Mean absolute oracle error", 100, "Per cent"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.7))
    for ax, (metric, title, scale, unit) in zip(axes, metrics):
        pivot = pooled.pivot(index="latency_hours", columns="official_gap_multiplier", values=metric)
        image = ax.imshow(pivot.to_numpy() * scale, origin="lower", cmap="magma", aspect="auto")
        ax.set_xticks(range(len(pivot.columns)), [f"{v:.1f}×" for v in pivot.columns])
        ax.set_yticks(range(len(pivot.index)), [f"{int(v)}" for v in pivot.index])
        ax.set_xlabel("Official/parallel gap multiplier")
        ax.set_ylabel("Oracle latency (hours)")
        ax.set_title(title)
        for i in range(len(pivot.index)):
            for j in range(len(pivot.columns)):
                value = pivot.iloc[i, j] * scale
                ax.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=8, color="white" if value > np.nanmedian(pivot.to_numpy() * scale) else "black")
        fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label=unit)
    fig.suptitle("Latency and official/parallel-rate disagreement compound oracle costs", fontsize=13.5, fontweight="bold")
    fig.tight_layout()
    save_figure(fig, "figure4_latency_basis_heatmap.png")


def figure_attack(attack: pd.DataFrame) -> None:
    pooled = attack.groupby(["architecture", "attack_scale"], as_index=False).mean(numeric_only=True)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5))
    for architecture in [MAIN_ARCHITECTURES[0].name, MAIN_ARCHITECTURES[-1].name]:
        subset = pooled[pooled["architecture"] == architecture]
        label = ARCH_SHORT[architecture]
        color = COLORS[architecture]
        axes[0].plot(subset["attack_scale"], 100 * subset["bad_debt_probability"], marker="o", lw=2.2, color=color, label=label)
        axes[1].plot(subset["attack_scale"], 100 * subset["p95_maximum_oracle_error"], marker="o", lw=2.2, color=color, label=label)
    axes[0].set_title("Bad-debt probability")
    axes[1].set_title("P95 maximum oracle error")
    for ax in axes:
        ax.set_xlabel("Attack magnitude multiplier")
        ax.set_ylabel("Per cent")
        ax.grid(alpha=0.22)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False)
    fig.suptitle("Robust medianization limits one-source collateral manipulation", fontsize=13.5, fontweight="bold")
    fig.tight_layout()
    save_figure(fig, "figure5_attack_robustness.png")


def figure_delay(delay: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.5))
    for currency, color in [("ARS", "#2E86AB"), ("TRY", "#F18F01")]:
        subset = delay[delay["currency"] == currency]
        axes[0].plot(subset["delay_hours"], 100 * subset["bad_debt_probability"], marker="o", lw=2.2, color=color, label=currency)
        axes[1].plot(subset["delay_hours"], 100 * subset["severe_depeg_probability"], marker="o", lw=2.2, color=color, label=currency)
    axes[0].set_title("Bad-debt probability")
    axes[1].set_title("Severe-depeg probability")
    for ax in axes:
        ax.set_xlabel("Parameter-execution delay (hours)")
        ax.set_ylabel("Per cent")
        ax.grid(alpha=0.22)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(frameon=False)
    fig.suptitle("Slow governance forfeits part of the adaptive controller's benefit", fontsize=13.5, fontweight="bold")
    fig.tight_layout()
    save_figure(fig, "figure6_governance_delay.png")


def figure_representative(representative: pd.DataFrame) -> None:
    data = representative[(representative["currency"] == "ARS") & (representative["path_id"] == 0)]
    fig, axes = plt.subplots(4, 1, figsize=(11.5, 10), sharex=True)
    for architecture in [MAIN_ARCHITECTURES[0].name, MAIN_ARCHITECTURES[-1].name]:
        subset = data[data["architecture"] == architecture]
        color = COLORS[architecture]
        label = ARCH_SHORT[architecture]
        days = subset["hour"] / 24
        axes[0].plot(days, 100 * subset["oracle_ratio_error"], color=color, lw=1.7, label=label)
        axes[1].plot(days, 100 * subset["dex_discount"], color=color, lw=1.9, label=label)
        axes[2].plot(days, 100 * subset["annual_rate"], color=color, lw=1.7, label=f"Rate: {label}")
        axes[2].plot(days, 100 * (subset["liquidation_ratio"] - 1), color=color, lw=1.3, ls="--", label=f"Buffer: {label}")
        axes[3].plot(days, subset["credit_cumulative"], color=color, lw=1.7, label=f"Credit: {label}")
        axes[3].plot(days, subset["bad_debt_cumulative"], color=color, lw=1.3, ls=":", label=f"Bad debt: {label}")
        if architecture == MAIN_ARCHITECTURES[-1].name:
            paused = subset["paused"].to_numpy().astype(bool)
            axes[1].fill_between(days, 0, 45, where=paused, color="#D1495B", alpha=0.10, step="mid", label="Breaker active")
    titles = ["Oracle ratio error", "DEX discount and breaker state", "Borrow rate (solid) and liquidation buffer over 100% (dashed)", "Cumulative credit (solid) and bad debt (dotted)"]
    ylabels = ["Per cent", "Per cent", "Per cent", "Initial-ceiling units"]
    for ax, title, ylabel in zip(axes, titles, ylabels):
        ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold")
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.20)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, ncol=3, fontsize=8, loc="upper left")
    axes[-1].set_xlabel("Days")
    fig.suptitle("Representative joint FX/collateral crisis path", fontsize=14, fontweight="bold")
    fig.tight_layout()
    save_figure(fig, "figure7_representative_crisis_path.png")


def write_validation(
    main: pd.DataFrame,
    historical: pd.DataFrame,
    latency: pd.DataFrame,
    attack: pd.DataFrame,
    delay: pd.DataFrame,
    ablation: pd.DataFrame,
) -> None:
    indexed = main.set_index(["currency", "architecture"])
    checks = [
        {
            "check": "main_rows",
            "passed": len(main) == 8,
            "detail": f"found {len(main)} architecture-currency rows",
        },
        {
            "check": "historical_windows",
            "passed": set(historical["paths"]) == {39},
            "detail": f"path counts {sorted(historical['paths'].unique())}",
        },
        {
            "check": "multi_oracle_improves_error",
            "passed": all(
                indexed.loc[(currency, "Adaptive multi-oracle"), "mean_oracle_error"]
                < indexed.loc[(currency, "Static single oracle"), "mean_oracle_error"]
                for currency in ["ARS", "TRY"]
            ),
            "detail": "adaptive multi-oracle MAE is below static single-oracle MAE",
        },
        {
            "check": "adaptive_reduces_bad_debt",
            "passed": all(
                indexed.loc[(currency, "Adaptive multi + breaker"), "bad_debt_probability"]
                < indexed.loc[(currency, "Static single oracle"), "bad_debt_probability"]
                for currency in ["ARS", "TRY"]
            ),
            "detail": "breaker architecture has lower bad-debt probability in both currencies",
        },
        {
            "check": "breaker_weakly_reduces_depeg",
            "passed": all(
                indexed.loc[(currency, "Adaptive multi + breaker"), "deep_depeg_probability"]
                <= indexed.loc[(currency, "Adaptive multi-oracle"), "deep_depeg_probability"]
                for currency in ["ARS", "TRY"]
            ),
            "detail": "breaker does not increase severe-depeg probability",
        },
        {
            "check": "finite_outputs",
            "passed": all(
                np.isfinite(frame.select_dtypes(include=[np.number]).to_numpy()).all()
                for frame in [main, historical, latency, attack, delay, ablation]
            ),
            "detail": "all numeric outputs are finite",
        },
    ]
    check_frame = pd.DataFrame(checks)
    check_frame.to_csv(RESULTS / "validation_checks.csv", index=False)
    if not check_frame["passed"].all():
        failures = check_frame.loc[~check_frame["passed"], "check"].tolist()
        raise RuntimeError(f"Validation failed: {failures}")

    anchors = {
        "seed": SEED,
        "main_paths_per_currency_architecture": N_PATHS,
        "historical_windows_per_currency": 39,
        "step_hours": CONFIG.step_hours,
        "horizon_days": CONFIG.n_steps * CONFIG.step_hours // 24,
        "ars_static_bad_debt_probability": float(
            indexed.loc[("ARS", "Static single oracle"), "bad_debt_probability"]
        ),
        "ars_breaker_bad_debt_probability": float(
            indexed.loc[("ARS", "Adaptive multi + breaker"), "bad_debt_probability"]
        ),
        "try_static_severe_depeg_probability": float(
            indexed.loc[("TRY", "Static single oracle"), "deep_depeg_probability"]
        ),
        "try_breaker_severe_depeg_probability": float(
            indexed.loc[("TRY", "Adaptive multi + breaker"), "deep_depeg_probability"]
        ),
        "ars_breaker_pause_share": float(
            indexed.loc[("ARS", "Adaptive multi + breaker"), "mean_pause_share"]
        ),
        "try_breaker_pause_share": float(
            indexed.loc[("TRY", "Adaptive multi + breaker"), "mean_pause_share"]
        ),
        "raw_ars_sha256": sha256(DATA / "raw_fx" / "ars_usd_fred.csv"),
        "raw_try_sha256": sha256(DATA / "raw_fx" / "try_usd_fred.csv"),
        "processed_panel_sha256": sha256(
            DATA / "processed" / "joint_monthly_market_panel.csv"
        ),
    }
    (RESULTS / "validation_anchors.json").write_text(
        json.dumps(anchors, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    ensure_dirs()
    panel = load_panel()
    main_results, _, representative, _ = run_main(panel)
    historical = run_historical(panel)
    latency = run_latency_basis_grid(panel)
    attack = run_attack_robustness(panel)
    delay = run_governance_delay(panel)
    ablation = run_controller_ablation(panel)
    make_tables(panel, main_results, latency, attack, delay, ablation)
    figure_architecture()
    figure_data(panel)
    figure_main(main_results)
    figure_latency_heatmap(latency)
    figure_attack(attack)
    figure_delay(delay)
    figure_representative(representative)
    write_validation(main_results, historical, latency, attack, delay, ablation)
    print(
        f"Completed {N_PATHS:,}-path main analysis, "
        f"{len(list(FIGURES.glob('*.png')))} figures, and "
        f"{len(list(TABLES.glob('*.tex')))} tables."
    )


if __name__ == "__main__":
    main()
