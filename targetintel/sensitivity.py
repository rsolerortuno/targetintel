"""One-weight-at-a-time sensitivity analysis for TargetIntel-IO."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from targetintel.benchmark import (
    DEFAULT_BENCHMARK_CONFIG_PATH,
    DEFAULT_NOT_PRIORITIZED_THRESHOLD,
    evaluate_benchmark,
)
from targetintel.intent_ranking import (
    DEFAULT_PROFILE_IDS,
    add_intent_ranks,
    add_opentargets_rank,
    add_rank_shift_vs_opentargets,
)
from targetintel.scoring import (
    DEFAULT_SCORING_CONFIGS,
    load_scoring_config,
    score_dataframe_with_config,
)


DEFAULT_SENSITIVITY_OUTPUT_DIR = Path("results/sensitivity")
DEFAULT_PERTURBATION_FRACTION = 0.20
DEFAULT_TOP_K_VALUES = (5, 10, 20)


@dataclass
class SensitivityAnalysis:
    """Container for all sensitivity-analysis outputs."""

    scenarios: pd.DataFrame
    summary: pd.DataFrame
    by_weight: pd.DataFrame
    target_rank_stability: pd.DataFrame
    metrics: dict[str, Any]


def _float(
    value: Any,
    default: float = 0.0,
) -> float:
    """Convert a potentially missing value into a float."""
    try:
        if value is None or pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_safe(value: Any) -> Any:
    """Recursively convert pandas and NumPy values into JSON-safe values."""
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item)
            for item in value
        ]

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


def load_scoring_configs(
    config_paths: Mapping[str, str | Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load all therapeutic-intent scoring configurations."""
    paths = config_paths or DEFAULT_SCORING_CONFIGS

    configs: dict[str, dict[str, Any]] = {}

    for profile_id, path in paths.items():
        config = load_scoring_config(path)

        configured_profile = config[
            "scoring_profile"
        ]["id"]

        if configured_profile != profile_id:
            raise ValueError(
                f"Config/profile mismatch for {profile_id!r}: "
                f"{configured_profile!r}"
            )

        configs[profile_id] = config

    return configs


def normalize_weights(
    weights: Mapping[str, Any],
) -> dict[str, float]:
    """Validate and normalize weights so that they sum to one."""
    numeric = {
        str(name): _float(
            value,
            default=float("nan"),
        )
        for name, value in weights.items()
    }

    if not numeric:
        raise ValueError(
            "Weights must be a non-empty mapping."
        )

    invalid_weights = [
        name
        for name, value in numeric.items()
        if pd.isna(value) or value < 0
    ]

    if invalid_weights:
        raise ValueError(
            "Weights must be numeric and non-negative: "
            f"{invalid_weights}"
        )

    total = sum(numeric.values())

    if total <= 0:
        raise ValueError(
            "At least one weight must be positive."
        )

    return {
        name: value / total
        for name, value in numeric.items()
    }


def perturb_config_weight(
    config: Mapping[str, Any],
    weight_name: str,
    multiplier: float,
) -> tuple[dict[str, Any], dict[str, float]]:
    """
    Perturb one scoring weight and renormalize the complete weight set.
    """
    if multiplier <= 0:
        raise ValueError(
            "multiplier must be greater than zero"
        )

    result = copy.deepcopy(dict(config))

    weights = {
        name: float(value)
        for name, value in result["weights"].items()
    }

    if weight_name not in weights:
        raise KeyError(
            f"Unknown scoring weight: {weight_name}"
        )

    weights[weight_name] *= multiplier

    normalized = normalize_weights(weights)
    result["weights"] = normalized

    return result, normalized


def prepare_feature_dataframe(
    input_df: pd.DataFrame,
    profile_ids: Iterable[str] = DEFAULT_PROFILE_IDS,
) -> pd.DataFrame:
    """
    Remove existing generated scores and rankings before rescoring.
    """
    required_columns = {
        "target_symbol",
        "opentargets_score",
        "role_classification",
    }

    missing_columns = sorted(
        required_columns - set(input_df.columns)
    )

    if missing_columns:
        raise KeyError(
            "Sensitivity input is missing columns: "
            f"{missing_columns}"
        )

    prefixes = tuple(
        f"{profile_id}_"
        for profile_id in profile_ids
    )

    generated_columns = [
        column
        for column in input_df.columns
        if (
            column == "opentargets_rank"
            or column.startswith(prefixes)
        )
    ]

    feature_df = input_df.drop(
        columns=generated_columns,
        errors="ignore",
    ).copy()

    feature_df["target_symbol"] = (
        feature_df["target_symbol"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    if feature_df["target_symbol"].eq("").any():
        raise ValueError(
            "Empty target symbols found."
        )

    duplicated_symbols = (
        feature_df.loc[
            feature_df[
                "target_symbol"
            ].duplicated(keep=False),
            "target_symbol",
        ]
        .unique()
        .tolist()
    )

    if duplicated_symbols:
        raise ValueError(
            "Duplicated target symbols: "
            f"{sorted(duplicated_symbols)[:20]}"
        )

    return feature_df.reset_index(drop=True)


def build_rankings_from_configs(
    feature_df: pd.DataFrame,
    configs: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """
    Score and rank a feature table using in-memory configurations.
    """
    profile_ids = list(configs)

    ranked_df = add_opentargets_rank(
        feature_df.copy()
    )

    for profile_id in profile_ids:
        ranked_df = score_dataframe_with_config(
            ranked_df,
            copy.deepcopy(
                dict(configs[profile_id])
            ),
        )

    ranked_df = add_intent_ranks(
        ranked_df,
        profile_ids=profile_ids,
    )

    ranked_df = add_rank_shift_vs_opentargets(
        ranked_df,
        profile_ids=profile_ids,
    )

    return ranked_df


def _top_set(
    ranked_df: pd.DataFrame,
    profile_id: str,
    top_k: int,
) -> set[str]:
    """Return the target symbols in one profile's top-k."""
    ranks = pd.to_numeric(
        ranked_df[f"{profile_id}_rank"],
        errors="coerce",
    )

    return set(
        ranked_df.loc[
            ranks.le(top_k),
            "target_symbol",
        ].astype(str)
    )


def _rank_metrics(
    baseline: pd.DataFrame,
    scenario: pd.DataFrame,
    profile_id: str,
    top_k_values: Iterable[int],
) -> tuple[dict[str, float], pd.DataFrame]:
    """
    Compare one perturbed ranking against its baseline.
    """
    rank_column = f"{profile_id}_rank"
    score_column = f"{profile_id}_final_score"

    baseline_columns = baseline[
        [
            "target_symbol",
            rank_column,
            score_column,
        ]
    ].rename(
        columns={
            rank_column: "baseline_rank",
            score_column: "baseline_score",
        }
    )

    scenario_columns = scenario[
        [
            "target_symbol",
            rank_column,
            score_column,
        ]
    ].rename(
        columns={
            rank_column: "scenario_rank",
            score_column: "scenario_score",
        }
    )

    comparison = baseline_columns.merge(
        scenario_columns,
        on="target_symbol",
        validate="one_to_one",
    )

    if len(comparison) != len(baseline):
        raise ValueError(
            "Baseline and scenario target sets differ."
        )

    comparison["rank_change"] = (
        comparison["scenario_rank"]
        - comparison["baseline_rank"]
    )

    comparison["absolute_rank_change"] = (
        comparison["rank_change"].abs()
    )

    comparison["score_change"] = (
        comparison["scenario_score"]
        - comparison["baseline_score"]
    )

    metrics: dict[str, float] = {
        "spearman_rank_correlation": float(
            comparison[
                "baseline_rank"
            ].corr(
                comparison["scenario_rank"]
            )
        ),
        "mean_absolute_rank_change": float(
            comparison[
                "absolute_rank_change"
            ].mean()
        ),
        "median_absolute_rank_change": float(
            comparison[
                "absolute_rank_change"
            ].median()
        ),
        "max_absolute_rank_change": float(
            comparison[
                "absolute_rank_change"
            ].max()
        ),
    }

    for top_k in top_k_values:
        baseline_top = _top_set(
            baseline,
            profile_id,
            top_k,
        )

        scenario_top = _top_set(
            scenario,
            profile_id,
            top_k,
        )

        shared_targets = len(
            baseline_top & scenario_top
        )

        union_targets = len(
            baseline_top | scenario_top
        )

        metrics[
            f"top_{top_k}_jaccard"
        ] = (
            shared_targets / union_targets
            if union_targets
            else 1.0
        )

        metrics[
            f"top_{top_k}_retention"
        ] = (
            shared_targets / len(baseline_top)
            if baseline_top
            else 1.0
        )

        metrics[
            f"top_{top_k}_shared_targets"
        ] = float(shared_targets)

        comparison[
            f"baseline_top_{top_k}"
        ] = comparison[
            "baseline_rank"
        ].le(top_k)

        comparison[
            f"scenario_top_{top_k}"
        ] = comparison[
            "scenario_rank"
        ].le(top_k)

    return metrics, comparison


def _intent_row(
    intent_metrics: pd.DataFrame,
    profile_id: str,
) -> dict[str, Any]:
    """Extract one profile's benchmark intent metrics."""
    matches = intent_metrics[
        intent_metrics["intent"].eq(profile_id)
    ]

    if len(matches) != 1:
        raise ValueError(
            f"Expected one intent row for {profile_id!r}, "
            f"found {len(matches)}."
        )

    return matches.iloc[0].to_dict()


def _add_delta(
    record: dict[str, Any],
    prefix: str,
    baseline: Mapping[str, Any],
    scenario: Mapping[str, Any],
    metric_names: Iterable[str],
) -> None:
    """Add baseline, scenario, and delta values to a record."""
    for metric_name in metric_names:
        baseline_value = _float(
            baseline.get(metric_name),
            default=float("nan"),
        )

        scenario_value = _float(
            scenario.get(metric_name),
            default=float("nan"),
        )

        record[
            f"baseline_{prefix}{metric_name}"
        ] = baseline_value

        record[
            f"scenario_{prefix}{metric_name}"
        ] = scenario_value

        record[
            f"delta_{prefix}{metric_name}"
        ] = (
            scenario_value - baseline_value
            if (
                not pd.isna(baseline_value)
                and not pd.isna(scenario_value)
            )
            else float("nan")
        )


def _aggregate_scenarios(
    scenarios: pd.DataFrame,
    group_columns: list[str],
    top_k_values: Iterable[int],
) -> pd.DataFrame:
    """Aggregate sensitivity scenarios by profile or profile/weight."""
    records: list[dict[str, Any]] = []

    grouped = scenarios.groupby(
        group_columns,
        sort=True,
        dropna=False,
    )

    for keys, group in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)

        record = dict(
            zip(
                group_columns,
                keys,
                strict=True,
            )
        )

        worst_scenario = group.loc[
            group[
                "spearman_rank_correlation"
            ].idxmin()
        ]

        record.update(
            {
                "scenario_count": int(len(group)),
                "minimum_spearman": group[
                    "spearman_rank_correlation"
                ].min(),
                "mean_spearman": group[
                    "spearman_rank_correlation"
                ].mean(),
                "minimum_spearman_scenario": (
                    worst_scenario["scenario_id"]
                ),
                "maximum_mean_absolute_rank_change": (
                    group[
                        "mean_absolute_rank_change"
                    ].max()
                ),
                "maximum_absolute_rank_change": (
                    group[
                        "max_absolute_rank_change"
                    ].max()
                ),
                "maximum_absolute_primary_intent_accuracy_delta": (
                    group[
                        "delta_benchmark_"
                        "primary_intent_accuracy_covered"
                    ]
                    .abs()
                    .max()
                ),
                "maximum_absolute_acceptable_intent_accuracy_delta": (
                    group[
                        "delta_benchmark_"
                        "acceptable_intent_accuracy_covered"
                    ]
                    .abs()
                    .max()
                ),
                "maximum_absolute_cross_intent_specificity_delta": (
                    group[
                        "delta_benchmark_"
                        "cross_intent_specificity_covered"
                    ]
                    .abs()
                    .max()
                ),
            }
        )

        for top_k in top_k_values:
            record[
                f"minimum_top_{top_k}_jaccard"
            ] = group[
                f"top_{top_k}_jaccard"
            ].min()

            record[
                f"mean_top_{top_k}_jaccard"
            ] = group[
                f"top_{top_k}_jaccard"
            ].mean()

            record[
                f"minimum_top_{top_k}_retention"
            ] = group[
                f"top_{top_k}_retention"
            ].min()

        records.append(record)

    result = pd.DataFrame(records)

    numeric_columns = result.select_dtypes(
        include="number"
    ).columns

    result[numeric_columns] = (
        result[numeric_columns].round(4)
    )

    return result


def _summarize_targets(
    details: pd.DataFrame,
    top_k_values: Iterable[int],
) -> pd.DataFrame:
    """Summarize per-target rank stability across all scenarios."""
    records: list[dict[str, Any]] = []

    grouped = details.groupby(
        [
            "profile_id",
            "target_symbol",
        ],
        sort=True,
    )

    for (
        profile_id,
        target_symbol,
    ), group in grouped:
        record: dict[str, Any] = {
            "profile_id": profile_id,
            "target_symbol": target_symbol,
            "baseline_rank": int(
                group["baseline_rank"].iloc[0]
            ),
            "baseline_score": (
                group["baseline_score"].iloc[0]
            ),
            "scenario_count": int(len(group)),
            "best_scenario_rank": int(
                group["scenario_rank"].min()
            ),
            "worst_scenario_rank": int(
                group["scenario_rank"].max()
            ),
            "mean_scenario_rank": (
                group["scenario_rank"].mean()
            ),
            "mean_absolute_rank_change": (
                group[
                    "absolute_rank_change"
                ].mean()
            ),
            "max_absolute_rank_change": int(
                group[
                    "absolute_rank_change"
                ].max()
            ),
            "mean_absolute_score_change": (
                group["score_change"]
                .abs()
                .mean()
            ),
            "max_absolute_score_change": (
                group["score_change"]
                .abs()
                .max()
            ),
        }

        for top_k in top_k_values:
            record[
                f"baseline_top_{top_k}"
            ] = bool(
                group[
                    f"baseline_top_{top_k}"
                ].iloc[0]
            )

            record[
                f"top_{top_k}_membership_rate"
            ] = group[
                f"scenario_top_{top_k}"
            ].mean()

        records.append(record)

    result = pd.DataFrame(records)

    numeric_columns = result.select_dtypes(
        include="number"
    ).columns

    result[numeric_columns] = (
        result[numeric_columns].round(4)
    )

    return result.sort_values(
        by=[
            "profile_id",
            "baseline_rank",
            "target_symbol",
        ]
    ).reset_index(drop=True)


def run_weight_sensitivity(
    input_df: pd.DataFrame,
    config_paths: Mapping[
        str,
        str | Path,
    ] | None = None,
    benchmark_config_path: str | Path = (
        DEFAULT_BENCHMARK_CONFIG_PATH
    ),
    perturbation_fraction: float = (
        DEFAULT_PERTURBATION_FRACTION
    ),
    top_k_values: Iterable[int] = (
        DEFAULT_TOP_K_VALUES
    ),
    not_prioritized_threshold: float = (
        DEFAULT_NOT_PRIORITIZED_THRESHOLD
    ),
) -> SensitivityAnalysis:
    """
    Run the complete one-weight-at-a-time sensitivity analysis.
    """
    if not 0 < perturbation_fraction < 1:
        raise ValueError(
            "perturbation_fraction must be between 0 and 1"
        )

    top_k_values = tuple(
        sorted(
            set(
                int(value)
                for value in top_k_values
            )
        )
    )

    if (
        not top_k_values
        or any(value <= 0 for value in top_k_values)
    ):
        raise ValueError(
            "top_k_values must contain positive integers"
        )

    configs = load_scoring_configs(
        config_paths
    )

    feature_df = prepare_feature_dataframe(
        input_df,
        profile_ids=configs,
    )

    if max(top_k_values) > len(feature_df):
        raise ValueError(
            "A top-k value exceeds the number of targets"
        )

    baseline_ranked = build_rankings_from_configs(
        feature_df,
        configs,
    )

    baseline_evaluation = evaluate_benchmark(
        baseline_ranked,
        config_path=benchmark_config_path,
        not_prioritized_threshold=(
            not_prioritized_threshold
        ),
    )

    baseline_intent_metrics = {
        profile_id: _intent_row(
            baseline_evaluation.intent_metrics,
            profile_id,
        )
        for profile_id in configs
    }

    benchmark_metric_names = (
        "primary_intent_accuracy_covered",
        "primary_intent_macro_f1_covered",
        "acceptable_intent_accuracy_covered",
        "cross_intent_specificity_covered",
        "control_not_prioritized_rate_covered",
        "mean_mode_top_5_recall_covered",
        "mean_mode_top_10_recall_covered",
        "mean_mode_top_20_recall_covered",
    )

    profile_metric_names = (
        "primary_intent_accuracy",
        "acceptable_intent_accuracy",
        "cross_intent_specificity",
        "mean_reciprocal_rank_all",
        "mean_rank_covered",
        "top_5_recall_all",
        "top_10_recall_all",
        "top_20_recall_all",
    )

    scenario_records: list[
        dict[str, Any]
    ] = []

    detail_frames: list[
        pd.DataFrame
    ] = []

    perturbation_percent = int(
        round(
            perturbation_fraction * 100
        )
    )

    for (
        profile_id,
        baseline_config,
    ) in configs.items():
        original_weights = {
            name: float(value)
            for name, value
            in baseline_config["weights"].items()
        }

        for (
            weight_name,
            original_weight,
        ) in original_weights.items():
            directions = (
                (
                    "minus",
                    1 - perturbation_fraction,
                ),
                (
                    "plus",
                    1 + perturbation_fraction,
                ),
            )

            for direction, multiplier in directions:
                scenario_id = (
                    f"{profile_id}__"
                    f"{weight_name}__"
                    f"{direction}"
                    f"{perturbation_percent}"
                )

                (
                    perturbed_config,
                    normalized_weights,
                ) = perturb_config_weight(
                    baseline_config,
                    weight_name,
                    multiplier,
                )

                scenario_configs = copy.deepcopy(
                    configs
                )

                scenario_configs[
                    profile_id
                ] = perturbed_config

                scenario_ranked = (
                    build_rankings_from_configs(
                        feature_df,
                        scenario_configs,
                    )
                )

                scenario_evaluation = (
                    evaluate_benchmark(
                        scenario_ranked,
                        config_path=(
                            benchmark_config_path
                        ),
                        not_prioritized_threshold=(
                            not_prioritized_threshold
                        ),
                    )
                )

                (
                    rank_metrics,
                    target_details,
                ) = _rank_metrics(
                    baseline_ranked,
                    scenario_ranked,
                    profile_id,
                    top_k_values,
                )

                record: dict[str, Any] = {
                    "scenario_id": scenario_id,
                    "perturbed_profile": profile_id,
                    "weight_name": weight_name,
                    "direction": direction,
                    "perturbation_fraction": (
                        perturbation_fraction
                    ),
                    "multiplier": multiplier,
                    "original_weight": (
                        original_weight
                    ),
                    "perturbed_raw_weight": (
                        original_weight
                        * multiplier
                    ),
                    "perturbed_normalized_weight": (
                        normalized_weights[
                            weight_name
                        ]
                    ),
                    "normalized_weights_json": (
                        json.dumps(
                            normalized_weights,
                            sort_keys=True,
                        )
                    ),
                    **rank_metrics,
                }

                _add_delta(
                    record,
                    prefix="benchmark_",
                    baseline=(
                        baseline_evaluation.summary
                    ),
                    scenario=(
                        scenario_evaluation.summary
                    ),
                    metric_names=(
                        benchmark_metric_names
                    ),
                )

                _add_delta(
                    record,
                    prefix="profile_",
                    baseline=(
                        baseline_intent_metrics[
                            profile_id
                        ]
                    ),
                    scenario=_intent_row(
                        scenario_evaluation[
                            "intent_metrics"
                        ]
                        if isinstance(
                            scenario_evaluation,
                            dict,
                        )
                        else scenario_evaluation.intent_metrics,
                        profile_id,
                    ),
                    metric_names=(
                        profile_metric_names
                    ),
                )

                scenario_records.append(
                    record
                )

                target_details.insert(
                    0,
                    "direction",
                    direction,
                )

                target_details.insert(
                    0,
                    "weight_name",
                    weight_name,
                )

                target_details.insert(
                    0,
                    "scenario_id",
                    scenario_id,
                )

                target_details.insert(
                    0,
                    "profile_id",
                    profile_id,
                )

                detail_frames.append(
                    target_details
                )

    scenarios = pd.DataFrame(
        scenario_records
    ).sort_values(
        by=[
            "perturbed_profile",
            "weight_name",
            "direction",
        ]
    ).reset_index(drop=True)

    numeric_columns = scenarios.select_dtypes(
        include="number"
    ).columns

    scenarios[numeric_columns] = (
        scenarios[numeric_columns].round(6)
    )

    target_details = pd.concat(
        detail_frames,
        ignore_index=True,
    )

    summary = _aggregate_scenarios(
        scenarios,
        group_columns=[
            "perturbed_profile",
        ],
        top_k_values=top_k_values,
    ).rename(
        columns={
            "perturbed_profile": "profile_id"
        }
    )

    by_weight = _aggregate_scenarios(
        scenarios,
        group_columns=[
            "perturbed_profile",
            "weight_name",
        ],
        top_k_values=top_k_values,
    ).rename(
        columns={
            "perturbed_profile": "profile_id"
        }
    )

    target_rank_stability = (
        _summarize_targets(
            target_details,
            top_k_values,
        )
    )

    metrics = {
        "analysis_id": (
            "targetintel_weight_sensitivity_v0_1"
        ),
        "analysis_type": (
            "one_weight_at_a_time"
        ),
        "perturbation_fraction": (
            perturbation_fraction
        ),
        "perturbation_percent": (
            perturbation_percent
        ),
        "scenario_count": len(
            scenarios
        ),
        "target_count": len(
            feature_df
        ),
        "profiles": list(
            configs
        ),
        "top_k_values": list(
            top_k_values
        ),
        "baseline_weights": {
            profile_id: normalize_weights(
                config["weights"]
            )
            for profile_id, config
            in configs.items()
        },
        "baseline_benchmark_summary": (
            baseline_evaluation.summary
        ),
        "profile_summary": (
            summary.to_dict(
                orient="records"
            )
        ),
        "interpretation": (
            "One top-level scoring weight is changed "
            "at a time and all weights are renormalized. "
            "Results measure local ranking robustness, "
            "not independent biological validation."
        ),
    }

    return SensitivityAnalysis(
        scenarios=scenarios,
        summary=summary,
        by_weight=by_weight,
        target_rank_stability=(
            target_rank_stability
        ),
        metrics=_json_safe(
            metrics
        ),
    )


def save_sensitivity_results(
    analysis: SensitivityAnalysis,
    output_dir: str | Path = (
        DEFAULT_SENSITIVITY_OUTPUT_DIR
    ),
) -> dict[str, Path]:
    """Save all sensitivity-analysis outputs."""
    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    paths = {
        "scenarios": (
            output_dir
            / "sensitivity_scenarios.csv"
        ),
        "summary": (
            output_dir
            / "sensitivity_summary.csv"
        ),
        "by_weight": (
            output_dir
            / "sensitivity_by_weight.csv"
        ),
        "target_rank_stability": (
            output_dir
            / "target_rank_stability.csv"
        ),
        "metrics": (
            output_dir
            / "sensitivity_metrics.json"
        ),
    }

    analysis.scenarios.to_csv(
        paths["scenarios"],
        index=False,
    )

    analysis.summary.to_csv(
        paths["summary"],
        index=False,
    )

    analysis.by_weight.to_csv(
        paths["by_weight"],
        index=False,
    )

    analysis.target_rank_stability.to_csv(
        paths["target_rank_stability"],
        index=False,
    )

    paths["metrics"].write_text(
        json.dumps(
            _json_safe(
                analysis.metrics
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return paths
