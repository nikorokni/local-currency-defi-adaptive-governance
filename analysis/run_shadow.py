#!/usr/bin/env python3
"""Command-line runner for historical replay and live read-only shadow mode."""

from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from risk_engine import RiskEngineConfig
from shadow_mode import (
    CSVObservationSource,
    HTTPJSONObservationSource,
    JSONLDecisionLog,
    ShadowRiskEngine,
    ShadowState,
    poll_live,
    replay,
)


def _only_known(data: dict[str, Any], cls: type[Any], label: str) -> dict[str, Any]:
    allowed = {field.name for field in fields(cls)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} keys: {', '.join(unknown)}")
    return data


def _resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be a JSON object")
    return config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the paper controller without protocol write access."
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--mode", choices=("replay", "once", "live"))
    parser.add_argument("--max-iterations", type=int)
    parser.add_argument(
        "--append",
        action="store_true",
        help="append to an existing JSONL log (default: start a fresh log)",
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    raw = load_config(config_path)
    base = config_path.parent
    mode = args.mode or raw.get("mode", "replay")

    controller_values = _only_known(
        dict(raw.get("controller", {})), RiskEngineConfig, "controller"
    )
    state_values = _only_known(
        dict(raw.get("initial_state", {})), ShadowState, "initial_state"
    )
    engine = ShadowRiskEngine(
        RiskEngineConfig(**controller_values),
        breaker_cooldown_steps=int(raw.get("breaker_cooldown_steps", 4)),
    )
    state = ShadowState(**state_values)

    output_path = _resolve(base, raw["output"]["jsonl_path"])
    if output_path.exists() and not args.append:
        output_path.unlink()
    log = JSONLDecisionLog(output_path)
    source_config = raw["source"]
    source_type = source_config["type"]

    if mode == "replay":
        if source_type != "csv":
            raise ValueError("replay mode requires a CSV source")
        source_path = _resolve(base, source_config["path"])
        decisions, state = replay(CSVObservationSource(source_path), engine, state, log)
        print(
            json.dumps(
                {
                    "mode": mode,
                    "observations": len(decisions),
                    "output": str(output_path),
                    "final_state": state.__dict__,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if source_type != "http_json":
        raise ValueError("once/live modes require an http_json source")
    source = HTTPJSONObservationSource(
        url=source_config["url"],
        field_map=source_config.get("field_map"),
        timeout_seconds=float(source_config.get("timeout_seconds", 10.0)),
        headers=source_config.get("headers"),
    )
    max_iterations = args.max_iterations
    if max_iterations is None:
        max_iterations = 1 if mode == "once" else int(raw.get("max_iterations", 0))
    state = poll_live(
        source,
        engine,
        state,
        log,
        interval_seconds=float(raw.get("poll_interval_seconds", 21_600)),
        max_iterations=max_iterations,
    )
    print(json.dumps({"mode": mode, "output": str(output_path), "final_state": state.__dict__}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
