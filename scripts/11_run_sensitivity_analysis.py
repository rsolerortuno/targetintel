#!/usr/bin/env python3

"""Run TargetIntel-IO weight-sensitivity analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from targetintel.benchmark import (
    DEFAULT_BENCHMARK_CONFIG_PATH,
    DEFAULT_NOT_PRIORITIZED_THRESHOLD,
)
from targetintel.sensitivity import (
    DEFAULT_PERTURBATION_FRACTION,
    DEFAULT_SENSITIVITY_OUTPUT_DIR,
    DEFAULT_TOP_K_VALUES,
    run_weight_sensitivity,
    save_sensitivity_results,
)


DEFAULT_INPUT_PATH = Path(
    "results/benchmark/"
    "ranked_targets_benchmark_universe.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Perturb each scoring weight by ±20%, "
            "rebuild rankings, and quantify ranking "
            "and benchmark stability."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
    )

    parser.add_argument(
        "--benchmark-config",
        type=Path,
        default=DEFAULT_BENCHMARK_CONFIG_PATH,
    )

    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_SENSITIVITY_OUTPUT_DIR,
    )

    parser.add_argument(
        "--perturbation",
        type=float,
        default=DEFAULT_PERTURBATION_FRACTION,
    )

    parser.add_argument(
        "--top-k",
        type=int,
        nargs="+",
        default=list(
            DEFAULT_TOP_K_VALUES
        ),
    )

    parser.add_argument(
        "--not-prioritized-threshold",
        type=float,
        default=(
            DEFAULT_NOT_PRIORITIZED_THRESHOLD
        ),
    )

    return parser.parse_args()


def validate_args(
    args: argparse.Namespace,
) -> None:
    if not args.input.is_file():
        raise FileNotFoundError(
            f"Input not found: {args.input}"
        )

    if not args.benchmark_config.is_file():
        raise FileNotFoundError(
            "Benchmark config not found: "
            f"{args.benchmark_config}"
        )

    if not 0 < args.perturbation < 1:
        raise ValueError(
            "--perturbation must be "
            "between 0 and 1"
        )

    if (
        not args.top_k
        or any(
            value <= 0
            for value in args.top_k
        )
    ):
        raise ValueError(
            "--top-k values must be positive"
        )

    if not (
        0
        <= args.not_prioritized_threshold
        <= 1
    ):
        raise ValueError(
            "--not-prioritized-threshold "
            "must be between 0 and 1"
        )


def main() -> None:
    args = parse_args()
    validate_args(args)

    print(
        f"Loading: {args.input}"
    )

    input_df = pd.read_csv(
        args.input
    )

    print(
        f"Rows: {len(input_df)}"
    )

    print(
        f"Columns: {len(input_df.columns)}"
    )

    print(
        "Perturbation: "
        f"±{args.perturbation * 100:.1f}%"
    )

    analysis = run_weight_sensitivity(
        input_df=input_df,
        benchmark_config_path=(
            args.benchmark_config
        ),
        perturbation_fraction=(
            args.perturbation
        ),
        top_k_values=args.top_k,
        not_prioritized_threshold=(
            args.not_prioritized_threshold
        ),
    )

    paths = save_sensitivity_results(
        analysis,
        output_dir=args.outdir,
    )

    summary_columns = [
        "profile_id",
        "scenario_count",
        "minimum_spearman",
        "mean_spearman",
        "minimum_top_5_jaccard",
        "minimum_top_10_jaccard",
        "minimum_top_20_jaccard",
        "minimum_top_10_retention",
        "maximum_mean_absolute_rank_change",
        "maximum_absolute_primary_intent_accuracy_delta",
        "minimum_spearman_scenario",
    ]

    available_summary_columns = [
        column
        for column in summary_columns
        if column in analysis.summary.columns
    ]

    print()
    print(
        "Weight-sensitivity summary"
    )
    print("=" * 110)

    print(
        analysis.summary[
            available_summary_columns
        ].to_string(index=False)
    )

    most_sensitive_weights = (
        analysis.by_weight
        .sort_values(
            by=[
                "profile_id",
                "minimum_spearman",
            ]
        )
        .groupby(
            "profile_id",
            as_index=False,
        )
        .head(1)
    )

    print()
    print(
        "Most sensitive weight per profile"
    )
    print("=" * 110)

    print(
        most_sensitive_weights[
            [
                "profile_id",
                "weight_name",
                "minimum_spearman",
                "minimum_top_10_jaccard",
                "minimum_top_20_jaccard",
                "maximum_mean_absolute_rank_change",
                "maximum_absolute_primary_intent_accuracy_delta",
            ]
        ].to_string(index=False)
    )

    sensitive_targets = (
        analysis.target_rank_stability
        .sort_values(
            by=[
                "profile_id",
                "max_absolute_rank_change",
                "mean_absolute_rank_change",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )
        .groupby(
            "profile_id",
            as_index=False,
        )
        .head(5)
    )

    print()
    print(
        "Five most rank-sensitive targets "
        "per profile"
    )
    print("=" * 110)

    print(
        sensitive_targets[
            [
                "profile_id",
                "target_symbol",
                "baseline_rank",
                "best_scenario_rank",
                "worst_scenario_rank",
                "mean_absolute_rank_change",
                "max_absolute_rank_change",
                "top_10_membership_rate",
            ]
        ].to_string(index=False)
    )

    print()
    print("Outputs")
    print("=" * 110)

    for name, path in paths.items():
        print(
            f"{name:24s} {path}"
        )

    print()
    print(
        "These results measure local robustness "
        "to one-weight-at-a-time perturbations, "
        "not independent biological validation."
    )


if __name__ == "__main__":
    main()
