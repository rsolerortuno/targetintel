"""
Internal benchmark utilities for TargetIntel-IO.

This module evaluates whether TargetIntel-IO behaves consistently with a
curated panel of expected biological roles and therapeutic intents.

The benchmark is an internal rule-based sanity validation. It is not an
independent clinical gold standard and does not establish therapeutic efficacy
or biomarker validity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)


DEFAULT_BENCHMARK_CONFIG_PATH = Path(
    "configs/benchmark_targets.yaml"
)

DEFAULT_BENCHMARK_OUTPUT_DIR = Path(
    "results/benchmark"
)

DEFAULT_MODE_IDS = (
    "antibody_io",
    "biomarker",
    "small_molecule",
)

NONE_INTENT = "none"
MISSING_PREDICTION = "__missing_prediction__"

DEFAULT_NOT_PRIORITIZED_THRESHOLD = 0.10


@dataclass
class BenchmarkEvaluation:
    """
    Container for all benchmark outputs.
    """

    predictions: pd.DataFrame
    summary: dict[str, Any]
    role_confusion_matrix: pd.DataFrame
    intent_metrics: pd.DataFrame


def _safe_str(value: Any) -> str:
    """
    Convert a potentially missing value into a clean string.
    """
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip()


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """
    Convert a potentially missing value into a float.
    """
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_symbol(value: Any) -> str:
    """
    Normalize a gene symbol for matching.
    """
    return _safe_str(value).upper()


def _round_metric(
    value: Any,
    digits: int = 4,
) -> float | None:
    """
    Round a metric while preserving missing values.
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return round(float(value), digits)


def load_benchmark_config(
    config_path: str | Path = DEFAULT_BENCHMARK_CONFIG_PATH,
) -> dict[str, Any]:
    """
    Load and validate the benchmark YAML configuration.

    Parameters
    ----------
    config_path:
        Path to the benchmark YAML file.

    Returns
    -------
    dict
        Parsed and validated benchmark configuration.
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(
            f"Benchmark configuration not found: {config_path}"
        )

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict):
        raise ValueError(
            "Benchmark configuration must be a YAML dictionary."
        )

    if "benchmark" not in config:
        raise ValueError(
            "Benchmark configuration is missing the 'benchmark' section."
        )

    if "groups" not in config:
        raise ValueError(
            "Benchmark configuration is missing the 'groups' section."
        )

    benchmark_metadata = config["benchmark"]
    groups = config["groups"]

    if not isinstance(benchmark_metadata, dict):
        raise ValueError(
            "'benchmark' must be a dictionary."
        )

    if not isinstance(groups, dict) or not groups:
        raise ValueError(
            "'groups' must be a non-empty dictionary."
        )

    required_metadata_fields = [
        "id",
        "version",
        "modes",
        "top_k_values",
    ]

    missing_metadata_fields = [
        field
        for field in required_metadata_fields
        if field not in benchmark_metadata
    ]

    if missing_metadata_fields:
        raise ValueError(
            "Benchmark metadata is missing required fields: "
            f"{missing_metadata_fields}"
        )

    modes = benchmark_metadata["modes"]

    if not isinstance(modes, list) or not modes:
        raise ValueError(
            "benchmark.modes must be a non-empty list."
        )

    invalid_modes = [
        mode
        for mode in modes
        if mode not in DEFAULT_MODE_IDS
    ]

    if invalid_modes:
        raise ValueError(
            f"Unsupported benchmark modes: {invalid_modes}"
        )

    top_k_values = benchmark_metadata["top_k_values"]

    if not isinstance(top_k_values, list) or not top_k_values:
        raise ValueError(
            "benchmark.top_k_values must be a non-empty list."
        )

    invalid_top_k_values = [
        value
        for value in top_k_values
        if not isinstance(value, int) or value <= 0
    ]

    if invalid_top_k_values:
        raise ValueError(
            "All top-k values must be positive integers: "
            f"{invalid_top_k_values}"
        )

    required_group_fields = [
        "label",
        "expected_role",
        "expected_primary_intent",
        "acceptable_intents",
        "targets",
    ]

    seen_symbols: set[str] = set()
    duplicate_symbols: list[str] = []

    valid_intents = set(modes) | {NONE_INTENT}

    for group_id, group in groups.items():
        if not isinstance(group, dict):
            raise ValueError(
                f"Benchmark group {group_id!r} must be a dictionary."
            )

        missing_group_fields = [
            field
            for field in required_group_fields
            if field not in group
        ]

        if missing_group_fields:
            raise ValueError(
                f"Benchmark group {group_id!r} is missing fields: "
                f"{missing_group_fields}"
            )

        primary_intent = group["expected_primary_intent"]

        if primary_intent not in valid_intents:
            raise ValueError(
                f"Invalid expected primary intent {primary_intent!r} "
                f"in benchmark group {group_id!r}."
            )

        acceptable_intents = group["acceptable_intents"]

        if not isinstance(acceptable_intents, list):
            raise ValueError(
                f"acceptable_intents must be a list in group {group_id!r}."
            )

        invalid_acceptable_intents = [
            intent
            for intent in acceptable_intents
            if intent not in modes
        ]

        if invalid_acceptable_intents:
            raise ValueError(
                f"Invalid acceptable intents in group {group_id!r}: "
                f"{invalid_acceptable_intents}"
            )

        targets = group["targets"]

        if not isinstance(targets, list) or not targets:
            raise ValueError(
                f"Benchmark group {group_id!r} must contain targets."
            )

        for symbol in targets:
            normalized_symbol = _normalize_symbol(symbol)

            if not normalized_symbol:
                raise ValueError(
                    f"Empty target symbol in benchmark group {group_id!r}."
                )

            if normalized_symbol in seen_symbols:
                duplicate_symbols.append(normalized_symbol)

            seen_symbols.add(normalized_symbol)

    if duplicate_symbols:
        raise ValueError(
            "Duplicate target symbols found in benchmark configuration: "
            f"{sorted(set(duplicate_symbols))}"
        )

    return config


def benchmark_config_to_dataframe(
    config: dict[str, Any],
) -> pd.DataFrame:
    """
    Convert the benchmark YAML configuration into one row per target.

    Parameters
    ----------
    config:
        Parsed benchmark configuration.

    Returns
    -------
    pandas.DataFrame
        Benchmark reference table.
    """
    records: list[dict[str, Any]] = []

    for group_id, group in config["groups"].items():
        acceptable_intents = list(
            group.get("acceptable_intents", [])
        )

        for symbol in group["targets"]:
            records.append(
                {
                    "target_symbol": _normalize_symbol(symbol),
                    "benchmark_group": group_id,
                    "benchmark_group_label": group["label"],
                    "expected_role": group["expected_role"],
                    "expected_primary_intent": (
                        group["expected_primary_intent"]
                    ),
                    "acceptable_intents": acceptable_intents.copy(),
                    "acceptable_intents_text": ";".join(
                        acceptable_intents
                    ),
                    "is_context_control": (
                        group["expected_primary_intent"] == NONE_INTENT
                    ),
                }
            )

    benchmark_df = pd.DataFrame(records)

    return benchmark_df.sort_values(
        by=[
            "expected_primary_intent",
            "benchmark_group",
            "target_symbol",
        ]
    ).reset_index(drop=True)


def _required_prediction_columns(
    modes: list[str] | tuple[str, ...],
) -> list[str]:
    """
    Return columns required from the ranked target table.
    """
    required_columns = [
        "target_symbol",
        "role_classification",
        "opentargets_score",
        "opentargets_rank",
    ]

    for mode in modes:
        required_columns.extend(
            [
                f"{mode}_final_score",
                f"{mode}_rank",
                f"{mode}_priority",
                f"{mode}_rank_shift_vs_opentargets",
            ]
        )

    return required_columns


def _validate_ranked_dataframe(
    ranked_df: pd.DataFrame,
    modes: list[str] | tuple[str, ...],
) -> None:
    """
    Validate the ranked TargetIntel-IO dataframe.
    """
    required_columns = _required_prediction_columns(modes)

    missing_columns = [
        column
        for column in required_columns
        if column not in ranked_df.columns
    ]

    if missing_columns:
        raise KeyError(
            "Ranked target table is missing required columns: "
            f"{missing_columns}"
        )

    normalized_symbols = (
        ranked_df["target_symbol"]
        .map(_normalize_symbol)
    )

    duplicated_symbols = sorted(
        normalized_symbols[
            normalized_symbols.duplicated(keep=False)
        ].unique()
    )

    if duplicated_symbols:
        raise ValueError(
            "Ranked target table contains duplicated target symbols: "
            f"{duplicated_symbols[:20]}"
        )


def _all_modes_not_prioritized(
    row: pd.Series,
    modes: list[str] | tuple[str, ...],
) -> bool:
    """
    Check whether every mode labels the target as not prioritized.
    """
    priorities = [
        _safe_str(row.get(f"{mode}_priority")).lower()
        for mode in modes
    ]

    return all(
        priority in {"", "not prioritized"}
        for priority in priorities
    )


def infer_predicted_primary_intent(
    row: pd.Series,
    modes: list[str] | tuple[str, ...],
    not_prioritized_threshold: float = (
        DEFAULT_NOT_PRIORITIZED_THRESHOLD
    ),
) -> tuple[str, float]:
    """
    Infer the target's predicted primary therapeutic intent.

    A target is assigned to ``none`` when all intent scores are at or below
    the not-prioritized threshold, or when every mode explicitly labels it as
    not prioritized.

    Missing benchmark targets receive ``__missing_prediction__``.
    """
    if not bool(row.get("prediction_available", False)):
        return MISSING_PREDICTION, 0.0

    mode_scores = {
        mode: _safe_float(
            row.get(f"{mode}_final_score"),
            default=0.0,
        )
        for mode in modes
    }

    best_mode = max(
        modes,
        key=lambda mode: mode_scores[mode],
    )

    best_score = mode_scores[best_mode]

    if (
        best_score <= not_prioritized_threshold
        or _all_modes_not_prioritized(row, modes)
    ):
        return NONE_INTENT, best_score

    return best_mode, best_score


def _acceptable_intent_correct(row: pd.Series) -> bool:
    """
    Check whether the predicted intent is acceptable for the target.
    """
    predicted_intent = row["predicted_primary_intent"]
    expected_intent = row["expected_primary_intent"]
    acceptable_intents = row["acceptable_intents"]

    if predicted_intent == MISSING_PREDICTION:
        return False

    if expected_intent == NONE_INTENT:
        return predicted_intent == NONE_INTENT

    return predicted_intent in acceptable_intents


def _add_intent_comparison_columns(
    predictions: pd.DataFrame,
    modes: list[str] | tuple[str, ...],
) -> pd.DataFrame:
    """
    Add expected-intent score, rank, shift, and specificity columns.
    """
    predictions = predictions.copy()

    expected_scores: list[float | None] = []
    max_off_intent_scores: list[float | None] = []
    score_margins: list[float | None] = []
    expected_mode_ranks: list[float | None] = []
    expected_mode_rank_shifts: list[float | None] = []
    expected_mode_priorities: list[str] = []
    control_max_scores: list[float | None] = []

    for _, row in predictions.iterrows():
        expected_intent = row["expected_primary_intent"]

        mode_scores = {
            mode: _safe_float(
                row.get(f"{mode}_final_score"),
                default=0.0,
            )
            for mode in modes
        }

        if not row["prediction_available"]:
            expected_scores.append(None)
            max_off_intent_scores.append(None)
            score_margins.append(None)
            expected_mode_ranks.append(None)
            expected_mode_rank_shifts.append(None)
            expected_mode_priorities.append("")
            control_max_scores.append(None)
            continue

        if expected_intent == NONE_INTENT:
            max_score = max(mode_scores.values())

            expected_scores.append(None)
            max_off_intent_scores.append(max_score)
            score_margins.append(None)
            expected_mode_ranks.append(None)
            expected_mode_rank_shifts.append(None)
            expected_mode_priorities.append("")
            control_max_scores.append(max_score)
            continue

        expected_score = mode_scores[expected_intent]

        off_intent_scores = [
            score
            for mode, score in mode_scores.items()
            if mode != expected_intent
        ]

        max_off_intent_score = max(off_intent_scores)

        expected_scores.append(expected_score)
        max_off_intent_scores.append(max_off_intent_score)
        score_margins.append(
            expected_score - max_off_intent_score
        )

        expected_mode_ranks.append(
            pd.to_numeric(
                row.get(f"{expected_intent}_rank"),
                errors="coerce",
            )
        )

        expected_mode_rank_shifts.append(
            pd.to_numeric(
                row.get(
                    f"{expected_intent}_rank_shift_vs_opentargets"
                ),
                errors="coerce",
            )
        )

        expected_mode_priorities.append(
            _safe_str(
                row.get(f"{expected_intent}_priority")
            )
        )

        control_max_scores.append(None)

    predictions["expected_intent_score"] = expected_scores
    predictions["max_off_intent_score"] = max_off_intent_scores
    predictions["intent_score_margin"] = score_margins
    predictions["expected_mode_rank"] = expected_mode_ranks
    predictions["expected_mode_rank_shift"] = (
        expected_mode_rank_shifts
    )
    predictions["expected_mode_priority"] = (
        expected_mode_priorities
    )
    predictions["control_max_score"] = control_max_scores

    predictions["expected_mode_is_top_score"] = (
        predictions["intent_score_margin"]
        .fillna(float("-inf"))
        .gt(0)
    )

    predictions.loc[
        predictions["expected_primary_intent"].eq(NONE_INTENT),
        "expected_mode_is_top_score",
    ] = False

    return predictions


def build_benchmark_predictions(
    ranked_df: pd.DataFrame,
    benchmark_config: dict[str, Any],
    not_prioritized_threshold: float = (
        DEFAULT_NOT_PRIORITIZED_THRESHOLD
    ),
) -> pd.DataFrame:
    """
    Merge benchmark expectations with TargetIntel-IO predictions.

    Parameters
    ----------
    ranked_df:
        TargetIntel-IO ranked target table.
    benchmark_config:
        Parsed benchmark configuration.
    not_prioritized_threshold:
        Maximum best-mode score interpreted as ``none``.

    Returns
    -------
    pandas.DataFrame
        One row per benchmark target with expected and predicted values.
    """
    modes = benchmark_config["benchmark"]["modes"]

    _validate_ranked_dataframe(
        ranked_df,
        modes=modes,
    )

    benchmark_df = benchmark_config_to_dataframe(
        benchmark_config
    )

    ranked_copy = ranked_df.copy()

    ranked_copy["target_symbol"] = (
        ranked_copy["target_symbol"]
        .map(_normalize_symbol)
    )

    columns_to_keep = _required_prediction_columns(modes)

    additional_columns = [
        "target_name",
        "best_modality",
        "therapeutic_direction",
        "resistance_axis",
        "confidence_level",
        "contradiction_score",
        "main_limitation",
    ]

    columns_to_keep.extend(
        column
        for column in additional_columns
        if column in ranked_copy.columns
    )

    ranked_copy = ranked_copy[
        list(dict.fromkeys(columns_to_keep))
    ].copy()

    predictions = benchmark_df.merge(
        ranked_copy,
        on="target_symbol",
        how="left",
        validate="one_to_one",
        indicator=True,
    )

    predictions["prediction_available"] = (
        predictions["_merge"].eq("both")
    )

    predictions = predictions.drop(columns="_merge")

    predictions = predictions.rename(
        columns={
            "role_classification": "predicted_role",
        }
    )

    predictions["predicted_role"] = (
        predictions["predicted_role"]
        .fillna(MISSING_PREDICTION)
        .map(_safe_str)
    )

    inferred_intents = predictions.apply(
        lambda row: infer_predicted_primary_intent(
            row,
            modes=modes,
            not_prioritized_threshold=(
                not_prioritized_threshold
            ),
        ),
        axis=1,
    )

    predictions["predicted_primary_intent"] = [
        value[0]
        for value in inferred_intents
    ]

    predictions["predicted_primary_intent_score"] = [
        value[1]
        for value in inferred_intents
    ]

    predictions["role_correct"] = (
        predictions["prediction_available"]
        & predictions["predicted_role"].eq(
            predictions["expected_role"]
        )
    )

    predictions["primary_intent_correct"] = (
        predictions["prediction_available"]
        & predictions["predicted_primary_intent"].eq(
            predictions["expected_primary_intent"]
        )
    )

    predictions["acceptable_intent_correct"] = (
        predictions.apply(
            _acceptable_intent_correct,
            axis=1,
        )
    )

    predictions = _add_intent_comparison_columns(
        predictions,
        modes=modes,
    )

    preferred_columns = [
        "target_symbol",
        "benchmark_group",
        "benchmark_group_label",
        "prediction_available",
        "expected_role",
        "predicted_role",
        "role_correct",
        "expected_primary_intent",
        "acceptable_intents_text",
        "predicted_primary_intent",
        "predicted_primary_intent_score",
        "primary_intent_correct",
        "acceptable_intent_correct",
        "expected_intent_score",
        "max_off_intent_score",
        "intent_score_margin",
        "expected_mode_is_top_score",
        "expected_mode_rank",
        "expected_mode_rank_shift",
        "expected_mode_priority",
        "control_max_score",
        "is_context_control",
        "opentargets_score",
        "opentargets_rank",
    ]

    for mode in modes:
        preferred_columns.extend(
            [
                f"{mode}_final_score",
                f"{mode}_rank",
                f"{mode}_priority",
                f"{mode}_rank_shift_vs_opentargets",
            ]
        )

    existing_preferred_columns = [
        column
        for column in preferred_columns
        if column in predictions.columns
    ]

    remaining_columns = [
        column
        for column in predictions.columns
        if column not in existing_preferred_columns
        and column != "acceptable_intents"
    ]

    return predictions[
        existing_preferred_columns + remaining_columns
    ].sort_values(
        by=[
            "prediction_available",
            "expected_primary_intent",
            "benchmark_group",
            "target_symbol",
        ],
        ascending=[
            False,
            True,
            True,
            True,
        ],
    ).reset_index(drop=True)


def calculate_role_confusion_matrix(
    predictions: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate the stable-role confusion matrix.

    Missing predictions are retained as an explicit prediction class.
    """
    expected_roles = predictions["expected_role"].astype(str)
    predicted_roles = predictions["predicted_role"].astype(str)

    labels = sorted(
        set(expected_roles)
        | set(predicted_roles)
    )

    matrix = confusion_matrix(
        expected_roles,
        predicted_roles,
        labels=labels,
    )

    confusion_df = pd.DataFrame(
        matrix,
        index=labels,
        columns=labels,
    )

    confusion_df.index.name = "expected_role"
    confusion_df.columns.name = "predicted_role"

    return confusion_df


def _classification_metrics(
    expected: pd.Series,
    predicted: pd.Series,
) -> dict[str, float]:
    """
    Calculate accuracy and macro classification metrics.
    """
    if len(expected) == 0:
        return {
            "accuracy": 0.0,
            "macro_precision": 0.0,
            "macro_recall": 0.0,
            "macro_f1": 0.0,
        }

    precision, recall, f1, _ = (
        precision_recall_fscore_support(
            expected,
            predicted,
            average="macro",
            zero_division=0,
        )
    )

    return {
        "accuracy": float(
            accuracy_score(expected, predicted)
        ),
        "macro_precision": float(precision),
        "macro_recall": float(recall),
        "macro_f1": float(f1),
    }


def calculate_intent_metrics(
    predictions: pd.DataFrame,
    benchmark_config: dict[str, Any],
) -> pd.DataFrame:
    """
    Calculate ranking and specificity metrics for each intent.

    Top-k recall is calculated against the global TargetIntel-IO rank, not a
    benchmark-only reranking.
    """
    benchmark_metadata = benchmark_config["benchmark"]
    modes = benchmark_metadata["modes"]
    top_k_values = benchmark_metadata["top_k_values"]

    records: list[dict[str, Any]] = []

    for mode in modes:
        mode_subset = predictions[
            predictions["expected_primary_intent"].eq(mode)
        ].copy()

        expected_count = len(mode_subset)

        covered_subset = mode_subset[
            mode_subset["prediction_available"]
        ].copy()

        covered_count = len(covered_subset)

        rank_column = f"{mode}_rank"
        shift_column = (
            f"{mode}_rank_shift_vs_opentargets"
        )
        score_column = f"{mode}_final_score"

        mode_subset[rank_column] = pd.to_numeric(
            mode_subset[rank_column],
            errors="coerce",
        )

        covered_subset[rank_column] = pd.to_numeric(
            covered_subset[rank_column],
            errors="coerce",
        )

        covered_subset[shift_column] = pd.to_numeric(
            covered_subset[shift_column],
            errors="coerce",
        )

        reciprocal_ranks_all = (
            1.0 / mode_subset[rank_column]
        ).replace(
            [float("inf"), float("-inf")],
            0.0,
        ).fillna(0.0)

        reciprocal_ranks_covered = (
            1.0 / covered_subset[rank_column]
        ).replace(
            [float("inf"), float("-inf")],
            0.0,
        ).dropna()

        record: dict[str, Any] = {
            "intent": mode,
            "expected_target_count": expected_count,
            "covered_target_count": covered_count,
            "coverage": (
                covered_count / expected_count
                if expected_count
                else 0.0
            ),
            "primary_intent_accuracy": (
                covered_subset[
                    "primary_intent_correct"
                ].mean()
                if covered_count
                else 0.0
            ),
            "acceptable_intent_accuracy": (
                covered_subset[
                    "acceptable_intent_correct"
                ].mean()
                if covered_count
                else 0.0
            ),
            "mean_reciprocal_rank_all": (
                reciprocal_ranks_all.mean()
                if expected_count
                else 0.0
            ),
            "mean_reciprocal_rank_covered": (
                reciprocal_ranks_covered.mean()
                if len(reciprocal_ranks_covered)
                else 0.0
            ),
            "mean_rank_covered": (
                covered_subset[rank_column].mean()
                if covered_count
                else None
            ),
            "mean_rank_shift_covered": (
                covered_subset[shift_column].mean()
                if covered_count
                else None
            ),
            "mean_expected_intent_score": (
                covered_subset[score_column].mean()
                if covered_count
                else None
            ),
            "mean_intent_score_margin": (
                covered_subset[
                    "intent_score_margin"
                ].mean()
                if covered_count
                else None
            ),
            "cross_intent_specificity": (
                covered_subset[
                    "expected_mode_is_top_score"
                ].mean()
                if covered_count
                else 0.0
            ),
        }

        for top_k in top_k_values:
            hits_all = (
                mode_subset[rank_column]
                .le(top_k)
                .fillna(False)
                .sum()
            )

            hits_covered = (
                covered_subset[rank_column]
                .le(top_k)
                .fillna(False)
                .sum()
            )

            record[f"top_{top_k}_hits"] = int(
                hits_all
            )

            record[f"top_{top_k}_recall_all"] = (
                hits_all / expected_count
                if expected_count
                else 0.0
            )

            record[
                f"top_{top_k}_recall_covered"
            ] = (
                hits_covered / covered_count
                if covered_count
                else 0.0
            )

        records.append(record)

    control_subset = predictions[
        predictions["expected_primary_intent"].eq(
            NONE_INTENT
        )
    ].copy()

    if not control_subset.empty:
        covered_controls = control_subset[
            control_subset["prediction_available"]
        ]

        records.append(
            {
                "intent": NONE_INTENT,
                "expected_target_count": len(
                    control_subset
                ),
                "covered_target_count": len(
                    covered_controls
                ),
                "coverage": (
                    len(covered_controls)
                    / len(control_subset)
                ),
                "primary_intent_accuracy": (
                    covered_controls[
                        "primary_intent_correct"
                    ].mean()
                    if len(covered_controls)
                    else 0.0
                ),
                "acceptable_intent_accuracy": (
                    covered_controls[
                        "acceptable_intent_correct"
                    ].mean()
                    if len(covered_controls)
                    else 0.0
                ),
                "mean_reciprocal_rank_all": None,
                "mean_reciprocal_rank_covered": None,
                "mean_rank_covered": None,
                "mean_rank_shift_covered": None,
                "mean_expected_intent_score": None,
                "mean_intent_score_margin": None,
                "cross_intent_specificity": None,
                "mean_control_max_score": (
                    covered_controls[
                        "control_max_score"
                    ].mean()
                    if len(covered_controls)
                    else None
                ),
            }
        )

    intent_metrics_df = pd.DataFrame(records)

    numeric_columns = intent_metrics_df.select_dtypes(
        include="number"
    ).columns

    intent_metrics_df[numeric_columns] = (
        intent_metrics_df[numeric_columns]
        .round(4)
    )

    return intent_metrics_df


def calculate_benchmark_summary(
    predictions: pd.DataFrame,
    intent_metrics: pd.DataFrame,
    benchmark_config: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate global benchmark summary metrics.
    """
    benchmark_metadata = benchmark_config["benchmark"]

    total_targets = len(predictions)

    covered_predictions = predictions[
        predictions["prediction_available"]
    ].copy()

    covered_targets = len(covered_predictions)

    role_metrics_all = _classification_metrics(
        predictions["expected_role"],
        predictions["predicted_role"],
    )

    role_metrics_covered = _classification_metrics(
        covered_predictions["expected_role"],
        covered_predictions["predicted_role"],
    )

    intent_metrics_all = _classification_metrics(
        predictions["expected_primary_intent"],
        predictions["predicted_primary_intent"],
    )

    intent_metrics_covered = _classification_metrics(
        covered_predictions[
            "expected_primary_intent"
        ],
        covered_predictions[
            "predicted_primary_intent"
        ],
    )

    non_control_covered = covered_predictions[
        covered_predictions[
            "expected_primary_intent"
        ].ne(NONE_INTENT)
    ]

    control_covered = covered_predictions[
        covered_predictions[
            "expected_primary_intent"
        ].eq(NONE_INTENT)
    ]

    scored_intent_rows = intent_metrics[
        intent_metrics["intent"].isin(
            benchmark_metadata["modes"]
        )
    ]

    summary: dict[str, Any] = {
        "benchmark_id": benchmark_metadata["id"],
        "benchmark_version": benchmark_metadata["version"],
        "validation_level": benchmark_metadata.get(
            "validation_level",
            "",
        ),
        "total_benchmark_targets": total_targets,
        "covered_benchmark_targets": covered_targets,
        "missing_benchmark_targets": (
            total_targets - covered_targets
        ),
        "benchmark_coverage": (
            covered_targets / total_targets
            if total_targets
            else 0.0
        ),
        "role_accuracy_all": (
            role_metrics_all["accuracy"]
        ),
        "role_macro_precision_all": (
            role_metrics_all["macro_precision"]
        ),
        "role_macro_recall_all": (
            role_metrics_all["macro_recall"]
        ),
        "role_macro_f1_all": (
            role_metrics_all["macro_f1"]
        ),
        "role_accuracy_covered": (
            role_metrics_covered["accuracy"]
        ),
        "role_macro_precision_covered": (
            role_metrics_covered[
                "macro_precision"
            ]
        ),
        "role_macro_recall_covered": (
            role_metrics_covered["macro_recall"]
        ),
        "role_macro_f1_covered": (
            role_metrics_covered["macro_f1"]
        ),
        "primary_intent_accuracy_all": (
            intent_metrics_all["accuracy"]
        ),
        "primary_intent_macro_f1_all": (
            intent_metrics_all["macro_f1"]
        ),
        "primary_intent_accuracy_covered": (
            intent_metrics_covered["accuracy"]
        ),
        "primary_intent_macro_f1_covered": (
            intent_metrics_covered["macro_f1"]
        ),
        "acceptable_intent_accuracy_all": (
            predictions[
                "acceptable_intent_correct"
            ].mean()
            if total_targets
            else 0.0
        ),
        "acceptable_intent_accuracy_covered": (
            covered_predictions[
                "acceptable_intent_correct"
            ].mean()
            if covered_targets
            else 0.0
        ),
        "cross_intent_specificity_covered": (
            non_control_covered[
                "expected_mode_is_top_score"
            ].mean()
            if len(non_control_covered)
            else 0.0
        ),
        "control_not_prioritized_rate_covered": (
            control_covered[
                "predicted_primary_intent"
            ].eq(NONE_INTENT).mean()
            if len(control_covered)
            else None
        ),
        "mean_control_max_score_covered": (
            control_covered[
                "control_max_score"
            ].mean()
            if len(control_covered)
            else None
        ),
        "mean_mode_mrr_all": (
            scored_intent_rows[
                "mean_reciprocal_rank_all"
            ].mean()
            if not scored_intent_rows.empty
            else 0.0
        ),
        "mean_mode_mrr_covered": (
            scored_intent_rows[
                "mean_reciprocal_rank_covered"
            ].mean()
            if not scored_intent_rows.empty
            else 0.0
        ),
    }

    for top_k in benchmark_metadata["top_k_values"]:
        column = f"top_{top_k}_recall_all"

        if column in scored_intent_rows.columns:
            summary[
                f"mean_mode_top_{top_k}_recall_all"
            ] = scored_intent_rows[column].mean()

        covered_column = (
            f"top_{top_k}_recall_covered"
        )

        if covered_column in scored_intent_rows.columns:
            summary[
                f"mean_mode_top_{top_k}_recall_covered"
            ] = scored_intent_rows[
                covered_column
            ].mean()

    rounded_summary: dict[str, Any] = {}

    for key, value in summary.items():
        if isinstance(value, float):
            rounded_summary[key] = _round_metric(value)
        else:
            rounded_summary[key] = value

    return rounded_summary


def evaluate_benchmark(
    ranked_df: pd.DataFrame,
    config_path: str | Path = DEFAULT_BENCHMARK_CONFIG_PATH,
    not_prioritized_threshold: float = (
        DEFAULT_NOT_PRIORITIZED_THRESHOLD
    ),
) -> BenchmarkEvaluation:
    """
    Run the complete TargetIntel-IO internal benchmark.

    Parameters
    ----------
    ranked_df:
        Ranked TargetIntel-IO target table.
    config_path:
        Path to the benchmark YAML configuration.
    not_prioritized_threshold:
        Best-mode score at or below which a target is interpreted as ``none``.

    Returns
    -------
    BenchmarkEvaluation
        Benchmark predictions, summary, role confusion matrix, and intent
        metrics.
    """
    benchmark_config = load_benchmark_config(
        config_path
    )

    predictions = build_benchmark_predictions(
        ranked_df=ranked_df,
        benchmark_config=benchmark_config,
        not_prioritized_threshold=(
            not_prioritized_threshold
        ),
    )

    role_confusion_df = (
        calculate_role_confusion_matrix(
            predictions
        )
    )

    intent_metrics_df = calculate_intent_metrics(
        predictions=predictions,
        benchmark_config=benchmark_config,
    )

    summary = calculate_benchmark_summary(
        predictions=predictions,
        intent_metrics=intent_metrics_df,
        benchmark_config=benchmark_config,
    )

    return BenchmarkEvaluation(
        predictions=predictions,
        summary=summary,
        role_confusion_matrix=role_confusion_df,
        intent_metrics=intent_metrics_df,
    )


def _json_safe(value: Any) -> Any:
    """
    Convert pandas and NumPy-like scalar values into JSON-safe values.
    """
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass

    return value


def save_benchmark_results(
    evaluation: BenchmarkEvaluation,
    output_dir: str | Path = DEFAULT_BENCHMARK_OUTPUT_DIR,
) -> dict[str, Path]:
    """
    Save all benchmark outputs.

    Generated files
    ---------------
    benchmark_predictions.csv
    benchmark_summary.csv
    benchmark_summary.json
    role_confusion_matrix.csv
    intent_metrics.csv
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    predictions_path = (
        output_dir / "benchmark_predictions.csv"
    )

    summary_csv_path = (
        output_dir / "benchmark_summary.csv"
    )

    summary_json_path = (
        output_dir / "benchmark_summary.json"
    )

    confusion_matrix_path = (
        output_dir / "role_confusion_matrix.csv"
    )

    intent_metrics_path = (
        output_dir / "intent_metrics.csv"
    )

    evaluation.predictions.to_csv(
        predictions_path,
        index=False,
    )

    summary_df = pd.DataFrame(
        [
            {
                "metric": key,
                "value": value,
            }
            for key, value in evaluation.summary.items()
        ]
    )

    summary_df.to_csv(
        summary_csv_path,
        index=False,
    )

    json_summary = {
        key: _json_safe(value)
        for key, value in evaluation.summary.items()
    }

    summary_json_path.write_text(
        json.dumps(
            json_summary,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    evaluation.role_confusion_matrix.to_csv(
        confusion_matrix_path,
    )

    evaluation.intent_metrics.to_csv(
        intent_metrics_path,
        index=False,
    )

    return {
        "benchmark_predictions": predictions_path,
        "benchmark_summary_csv": summary_csv_path,
        "benchmark_summary_json": summary_json_path,
        "role_confusion_matrix": confusion_matrix_path,
        "intent_metrics": intent_metrics_path,
    }
