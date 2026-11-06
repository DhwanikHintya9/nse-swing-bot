"""Descriptive, research-only evaluation of point-in-time event cohorts."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

REQUIRED_RESEARCH_COLUMNS = (
    "signal",
    "event_count_30d",
    "has_high_materiality_event_30d",
    "unassessed_impact_count_30d",
    "positive_event_count_30d",
    "negative_event_count_30d",
    "mixed_event_count_30d",
)
REQUIRED_COVERAGE_COLUMNS = (
    "coverage_complete_30d",
    "coverage_snapshot_id",
    "covered_from",
    "covered_through",
    "captured_at",
)
SUMMARY_COLUMNS = (
    "cohort",
    "horizon_sessions",
    "observation_count",
    "complete_label_count",
    "censored_label_count",
    "label_completion_rate",
    "sample_sufficient",
    "mean_forward_close_return",
    "median_forward_close_return",
    "p10_forward_close_return",
    "p25_forward_close_return",
    "p75_forward_close_return",
    "p90_forward_close_return",
    "positive_return_count",
    "positive_return_rate",
    "positive_return_wilson_95_low",
    "positive_return_wilson_95_high",
    "median_return_bootstrap_95_low",
    "median_return_bootstrap_95_high",
    "median_max_favorable_excursion",
    "median_max_adverse_excursion",
)

_Z_95 = 1.959963984540054


def _aware_timestamp(value: object, field: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return timestamp


def _coverage_is_complete(
    row: pd.Series,
    decision_at: pd.Timestamp,
    decision_date: date,
) -> bool:
    complete = row["coverage_complete_30d"]
    if not isinstance(complete, (bool, np.bool_)):
        raise ValueError("coverage_complete_30d must contain non-null booleans")
    if not complete:
        return False

    snapshot_id = row["coverage_snapshot_id"]
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError("complete event coverage requires coverage_snapshot_id")
    try:
        covered_from = pd.Timestamp(row["covered_from"]).date()
        covered_through = pd.Timestamp(row["covered_through"]).date()
    except (TypeError, ValueError) as error:
        raise ValueError("complete event coverage requires valid covered_from/covered_through") from error
    captured_at = _aware_timestamp(row["captured_at"], "coverage captured_at")
    if captured_at > decision_at:
        raise ValueError("complete event coverage was captured after its decision timestamp")
    if covered_from > decision_date - timedelta(days=30):
        raise ValueError("complete event coverage does not cover the full 30-day lookback")
    if covered_through < decision_date:
        raise ValueError("complete event coverage does not reach the decision date")
    return True


def _wilson_interval(successes: int, total: int) -> tuple[float | None, float | None]:
    if total == 0:
        return None, None
    proportion = successes / total
    denominator = 1.0 + _Z_95**2 / total
    center = (proportion + _Z_95**2 / (2.0 * total)) / denominator
    margin = (
        _Z_95
        * np.sqrt(
            proportion * (1.0 - proportion) / total
            + _Z_95**2 / (4.0 * total**2)
        )
        / denominator
    )
    return float(max(0.0, center - margin)), float(min(1.0, center + margin))


def _median_bootstrap_interval(
    values: np.ndarray,
    cohort: str,
    horizon: int,
    samples: int,
    random_seed: int,
) -> tuple[float | None, float | None]:
    if values.size == 0:
        return None, None
    if values.size == 1:
        value = float(values[0])
        return value, value
    seed_material = f"{random_seed}:{cohort}:{horizon}".encode()
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:8], "big")
    generator = np.random.default_rng(seed)
    medians = np.empty(samples, dtype=float)
    for sample_index in range(samples):
        sample_indices = generator.integers(0, values.size, size=values.size)
        medians[sample_index] = np.median(values[sample_indices])
    lower, upper = np.quantile(medians, [0.025, 0.975])
    return float(lower), float(upper)


def build_event_cohort_summary(
    research_frame: pd.DataFrame,
    coverage_frame: pd.DataFrame,
    outcome_labels: pd.DataFrame,
    symbol: str,
    min_sample_size: int = 30,
    bootstrap_samples: int = 2000,
    random_seed: int = 2026,
) -> pd.DataFrame:
    """Summarize predeclared event cohorts among unchanged Phase 1 signals.

    All rows in the baseline cohort remain present regardless of event
    coverage. Event/no-event cohorts require an explicit complete 30-day
    point-in-time coverage record. Censored outcome labels count toward the
    cohort denominator but are excluded from return statistics.
    """
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")
    if min_sample_size < 1:
        raise ValueError("min_sample_size must be positive")
    if bootstrap_samples < 100:
        raise ValueError("bootstrap_samples must be at least 100")

    for name, frame in (
        ("research_frame", research_frame),
        ("coverage_frame", coverage_frame),
    ):
        if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
            raise ValueError(f"{name} index must be a timezone-aware DatetimeIndex")
        if frame.index.has_duplicates or frame.index.hasnans:
            raise ValueError(f"{name} index must be unique and cannot contain NaT")
        if not frame.index.is_monotonic_increasing:
            raise ValueError(f"{name} index must be strictly increasing")

    if not research_frame.index.equals(coverage_frame.index):
        raise ValueError("research_frame and coverage_frame indexes must match exactly")
    missing_research = set(REQUIRED_RESEARCH_COLUMNS).difference(research_frame.columns)
    if missing_research:
        raise ValueError(
            "research_frame is missing required columns: "
            + ", ".join(sorted(missing_research))
        )
    missing_coverage = set(REQUIRED_COVERAGE_COLUMNS).difference(coverage_frame.columns)
    if missing_coverage:
        raise ValueError(
            "coverage_frame is missing required columns: "
            + ", ".join(sorted(missing_coverage))
        )
    if not research_frame["signal"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    ).all():
        raise ValueError("Phase 1 signal column must contain non-null booleans")
    if not research_frame["has_high_materiality_event_30d"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    ).all():
        raise ValueError("high-materiality feature must contain non-null booleans")

    source_count_columns = (
        "event_count_30d",
        "unassessed_impact_count_30d",
        "positive_event_count_30d",
        "negative_event_count_30d",
        "mixed_event_count_30d",
    )
    counts = research_frame.loc[:, list(source_count_columns)].apply(
        pd.to_numeric, errors="coerce"
    )
    count_values = counts.to_numpy(dtype=float)
    if (
        not np.isfinite(count_values).all()
        or (count_values < 0).any()
        or (count_values % 1 != 0).any()
    ):
        raise ValueError("event count features must be finite non-negative integers")

    if outcome_labels.empty:
        raise ValueError("outcome_labels must not be empty")
    required_label_columns = {
        "symbol",
        "decision_at",
        "horizon_sessions",
        "forward_close_return",
        "max_favorable_excursion",
        "max_adverse_excursion",
        "label_status",
    }
    missing_labels = required_label_columns.difference(outcome_labels.columns)
    if missing_labels:
        raise ValueError(
            "outcome_labels are missing required columns: "
            + ", ".join(sorted(missing_labels))
        )
    labels = outcome_labels.copy()
    labels["symbol"] = labels["symbol"].astype(str).str.upper()
    if set(labels["symbol"]) != {normalized_symbol}:
        raise ValueError("outcome_labels must contain only the requested symbol")
    if labels["horizon_sessions"].isna().any():
        raise ValueError("outcome label horizons cannot be null")
    numeric_horizons = pd.to_numeric(labels["horizon_sessions"], errors="raise")
    if (numeric_horizons % 1 != 0).any():
        raise ValueError("outcome label horizons must be whole trading-session counts")
    labels["horizon_sessions"] = numeric_horizons.astype(int)
    if (labels["horizon_sessions"] <= 0).any():
        raise ValueError("outcome label horizons must be positive")
    if not labels["label_status"].isin(["complete", "censored"]).all():
        raise ValueError("outcome label status must be complete or censored")
    parsed_decisions: list[pd.Timestamp] = []
    for value in labels["decision_at"]:
        timestamp = _aware_timestamp(value, "outcome label decision_at")
        parsed_decisions.append(timestamp.tz_convert("UTC"))
    labels["_decision_utc"] = pd.DatetimeIndex(parsed_decisions)
    if labels.duplicated(["symbol", "_decision_utc", "horizon_sessions"]).any():
        raise ValueError("outcome labels contain duplicate symbol/decision/horizon keys")

    horizons = tuple(sorted(int(value) for value in labels["horizon_sessions"].unique()))
    research_keys = {
        timestamp.tz_convert("UTC") for timestamp in research_frame.index
    }
    label_keys = set(labels["_decision_utc"])
    if not label_keys.issubset(research_keys):
        raise ValueError("outcome labels contain decision timestamps outside research_frame")
    signal_rows = research_frame.loc[research_frame["signal"]].copy()
    if signal_rows.empty:
        raise ValueError("research_frame must contain at least one Phase 1 signal")
    signal_keys = {
        timestamp.tz_convert("UTC") for timestamp in signal_rows.index
    }
    available_keys = set(labels["_decision_utc"])
    for key in signal_keys:
        if key not in available_keys:
            raise ValueError("outcome labels are missing a Phase 1 signal decision timestamp")
    for key in signal_keys:
        rows_for_decision = labels.loc[labels["_decision_utc"] == key]
        if set(rows_for_decision["horizon_sessions"]) != set(horizons):
            raise ValueError("outcome labels do not cover every horizon for each signal")

    # Construct signal-only observation records without modifying caller inputs.
    observation_rows: list[dict[str, object]] = []
    coverage_by_index = coverage_frame
    for decision_at, row in signal_rows.iterrows():
        coverage_row = coverage_by_index.loc[decision_at]
        complete = _coverage_is_complete(
            coverage_row,
            decision_at,
            decision_at.tz_convert("Asia/Kolkata").date(),
        )
        for horizon in horizons:
            key = (decision_at.tz_convert("UTC"), horizon)
            label_row = labels.loc[
                (labels["_decision_utc"] == key[0])
                & (labels["horizon_sessions"] == horizon)
            ].iloc[0]
            observation_rows.append(
                {
                    "decision_at": decision_at,
                    "horizon_sessions": horizon,
                    "coverage_complete": complete,
                    "event_count_30d": float(row["event_count_30d"]),
                    "has_high_materiality_event_30d": bool(
                        row["has_high_materiality_event_30d"]
                    ),
                    "unassessed_impact_count_30d": float(
                        row["unassessed_impact_count_30d"]
                    ),
                    "positive_event_count_30d": float(row["positive_event_count_30d"]),
                    "negative_event_count_30d": float(row["negative_event_count_30d"]),
                    "mixed_event_count_30d": float(row["mixed_event_count_30d"]),
                    "label_status": label_row["label_status"],
                    "forward_close_return": label_row["forward_close_return"],
                    "max_favorable_excursion": label_row["max_favorable_excursion"],
                    "max_adverse_excursion": label_row["max_adverse_excursion"],
                }
            )
    observations = pd.DataFrame(observation_rows)

    summaries: list[dict[str, object]] = []
    for horizon in horizons:
        horizon_rows = observations.loc[
            observations["horizon_sessions"] == horizon
        ].reset_index(drop=True)
        complete_coverage = horizon_rows["coverage_complete"]
        cohorts: list[tuple[str, pd.Series]] = [
            ("all_phase1_signals", pd.Series(True, index=horizon_rows.index)),
            ("event_coverage_complete", complete_coverage),
            ("event_coverage_incomplete_or_unavailable", ~complete_coverage),
            (
                "admitted_event_present_30d",
                complete_coverage & (horizon_rows["event_count_30d"] > 0),
            ),
            (
                "no_admitted_event_in_complete_30d_window",
                complete_coverage & (horizon_rows["event_count_30d"] == 0),
            ),
            (
                "high_materiality_event_present_30d",
                complete_coverage & horizon_rows["has_high_materiality_event_30d"],
            ),
            (
                "unassessed_impact_present_30d",
                complete_coverage & (horizon_rows["unassessed_impact_count_30d"] > 0),
            ),
            (
                "positive_impact_assessed_30d",
                complete_coverage & (horizon_rows["positive_event_count_30d"] > 0),
            ),
            (
                "negative_impact_assessed_30d",
                complete_coverage & (horizon_rows["negative_event_count_30d"] > 0),
            ),
            (
                "mixed_impact_assessed_30d",
                complete_coverage & (horizon_rows["mixed_event_count_30d"] > 0),
            ),
        ]
        for cohort_name, cohort_mask in cohorts:
            selected = horizon_rows.loc[cohort_mask.to_numpy()]
            complete = selected.loc[selected["label_status"] == "complete"]
            censored_count = int((selected["label_status"] == "censored").sum())
            returns = pd.to_numeric(
                complete["forward_close_return"], errors="coerce"
            ).to_numpy(dtype=float)
            if not np.isfinite(returns).all():
                raise ValueError("complete outcome labels must have finite forward returns")
            positive_count = int((returns > 0).sum())
            win_rate = positive_count / len(returns) if len(returns) else None
            wilson_low, wilson_high = _wilson_interval(positive_count, len(returns))
            median_low, median_high = _median_bootstrap_interval(
                returns, cohort_name, horizon, bootstrap_samples, random_seed
            )
            mfe = pd.to_numeric(
                complete["max_favorable_excursion"], errors="coerce"
            ).to_numpy(dtype=float)
            mae = pd.to_numeric(
                complete["max_adverse_excursion"], errors="coerce"
            ).to_numpy(dtype=float)
            if not np.isfinite(mfe).all() or not np.isfinite(mae).all():
                raise ValueError("complete outcome labels must have finite excursion values")

            quantiles = (
                np.quantile(returns, [0.10, 0.25, 0.75, 0.90])
                if len(returns)
                else [None, None, None, None]
            )
            summaries.append(
                {
                    "cohort": cohort_name,
                    "horizon_sessions": horizon,
                    "observation_count": len(selected),
                    "complete_label_count": len(complete),
                    "censored_label_count": censored_count,
                    "label_completion_rate": (
                        len(complete) / len(selected) if len(selected) else None
                    ),
                    "sample_sufficient": len(complete) >= min_sample_size,
                    "mean_forward_close_return": (
                        float(np.mean(returns)) if len(returns) else None
                    ),
                    "median_forward_close_return": (
                        float(np.median(returns)) if len(returns) else None
                    ),
                    "p10_forward_close_return": quantiles[0],
                    "p25_forward_close_return": quantiles[1],
                    "p75_forward_close_return": quantiles[2],
                    "p90_forward_close_return": quantiles[3],
                    "positive_return_count": positive_count,
                    "positive_return_rate": win_rate,
                    "positive_return_wilson_95_low": wilson_low,
                    "positive_return_wilson_95_high": wilson_high,
                    "median_return_bootstrap_95_low": median_low,
                    "median_return_bootstrap_95_high": median_high,
                    "median_max_favorable_excursion": (
                        float(np.median(mfe)) if len(mfe) else None
                    ),
                    "median_max_adverse_excursion": (
                        float(np.median(mae)) if len(mae) else None
                    ),
                }
            )

    return pd.DataFrame(summaries, columns=SUMMARY_COLUMNS)
