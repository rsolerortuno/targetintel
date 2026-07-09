#!/usr/bin/env python3

"""
Run the TargetIntel-IO internal therapeutic-intent benchmark.

This script:

1. Loads an existing ranked-target table, or rebuilds it when necessary.
2. Loads the curated benchmark configuration.
3. Evaluates stable-role classification and therapeutic-intent ranking.
4. Saves benchmark predictions, summary metrics, intent metrics, and the
   role confusion matrix.

This benchmark is an internal rule-based sanity validation. It is not an
independent clinical gold standard and does not establish therapeutic efficacy
or biomarker validity.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from targetintel.benchmark import (
    DEFAULT_BENCHMARK_CONFIG_PATH,
    DEFAULT_BENCHMARK_OUTPUT_DIR,
    DEFAULT_NOT_PRIORITIZED_THRESHOLD,
    evaluate_benchmark,
    save_benchmark_results,
)
from targetintel.feature_table import build_feature_table
from targetintel.intent_ranking import (
    build_intent_rankings,
    save_ranked_targets,
)


DEFAULT_RANKED_TARGETS_PATH = Path("results/ranked_targets.csv")


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run the TargetIntel-IO internal therapeutic-intent benchmark."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_RANKED_TARGETS_PATH,
        help=(
            "Existing ranked-target CSV. "
            "Default: results/ranked_targets.csv"
        ),
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_BENCHMARK_CONFIG_PATH,
        help=(
            "Curated benchmark YAML configuration. "
            "Default: configs/benchmark_targets.yaml"
        ),
    )

    parser.add_argument(
        "--outdir",
        type=Path,
        default=DEFAULT_BENCHMARK_OUTPUT_DIR,
        help=(
            "Directory where benchmark outputs will be written. "
            "Default: results/benchmark"
        ),
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help=(
            "Number of Open Targets records requested per API page "
            "when rebuilding the ranked table."
        ),
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help=(
            "Maximum number of Open Targets API pages retrieved "
            "when rebuilding the ranked table."
        ),
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Refresh cached Open Targets data when rebuilding "
            "the ranked table."
        ),
    )

    parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "Rebuild the feature table and rankings even when the input "
            "ranked-target CSV already exists."
        ),
    )

    parser.add_argument(
        "--not-prioritized-threshold",
        type=float,
        default=DEFAULT_NOT_PRIORITIZED_THRESHOLD,
        help=(
            "Maximum best-mode score interpreted as 'none'. "
            f"Default: {DEFAULT_NOT_PRIORITIZED_THRESHOLD}"
        ),
    )

    parser.add_argument(
        "--show-missing",
        action="store_true",
        help="Print all benchmark targets missing from the ranked table.",
    )

    parser.add_argument(
        "--show-errors",
        action="store_true",
        help=(
            "Print benchmark targets with incorrect role or "
            "primary-intent predictions."
        ),
    )

    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    """
    Validate command-line arguments.
    """
    if args.page_size <= 0:
        raise ValueError("--page-size must be greater than zero.")

    if args.max_pages <= 0:
        raise ValueError("--max-pages must be greater than zero.")

    if not 0 <= args.not_prioritized_threshold <= 1:
        raise ValueError(
            "--not-prioritized-threshold must be between 0 and 1."
        )

    if not args.config.exists():
        raise FileNotFoundError(
            f"Benchmark configuration not found: {args.config}"
        )


def load_or_build_ranked_targets(
    input_path: Path,
    page_size: int,
    max_pages: int,
    refresh: bool,
    rebuild: bool,
) -> pd.DataFrame:
    """
    Load an existing ranked-target table or rebuild it.

    Parameters
    ----------
    input_path:
        Ranked-target CSV path.
    page_size:
        Open Targets page size used during rebuilding.
    max_pages:
        Maximum Open Targets pages used during rebuilding.
    refresh:
        Whether to refresh the Open Targets cache.
    rebuild:
        Whether to rebuild even if the input CSV exists.

    Returns
    -------
    pandas.DataFrame
        Ranked TargetIntel-IO target table.
    """
    if input_path.exists() and not rebuild:
        print(f"Loading ranked targets from: {input_path}")

        ranked_df = pd.read_csv(input_path)

        print(f"Loaded rows: {len(ranked_df)}")
        print(f"Loaded columns: {len(ranked_df.columns)}")

        return ranked_df

    if rebuild:
        print("Rebuilding ranked targets because --rebuild was supplied.")
    else:
        print(
            f"Ranked-target table not found at {input_path}. "
            "Rebuilding it."
        )

    feature_df = build_feature_table(
        page_size=page_size,
        max_pages=max_pages,
        refresh=refresh,
    )

    print(f"Feature-table rows: {len(feature_df)}")
    print(f"Feature-table columns: {len(feature_df.columns)}")

    ranked_df = build_intent_rankings(feature_df)

    save_ranked_targets(
        ranked_df,
        output_path=input_path,
    )

    print(f"Saved rebuilt ranked targets to: {input_path}")

    return ranked_df


def print_summary(summary: dict[str, object]) -> None:
    """
    Print selected benchmark summary metrics.
    """
    preferred_metrics = [
        "benchmark_id",
        "benchmark_version",
        "validation_level",
        "total_benchmark_targets",
        "covered_benchmark_targets",
        "missing_benchmark_targets",
        "benchmark_coverage",
        "opentargets_retrieved_benchmark_targets",
        "opentargets_retrieval_coverage",
        "targetintel_evaluation_coverage",
        "role_accuracy_all",
        "role_macro_f1_all",
        "role_accuracy_covered",
        "role_macro_f1_covered",
        "primary_intent_accuracy_all",
        "primary_intent_macro_f1_all",
        "primary_intent_accuracy_covered",
        "primary_intent_macro_f1_covered",
        "acceptable_intent_accuracy_all",
        "acceptable_intent_accuracy_covered",
        "cross_intent_specificity_covered",
        "control_not_prioritized_rate_covered",
        "mean_control_max_score_covered",
        "mean_mode_mrr_all",
        "mean_mode_mrr_covered",
        "mean_mode_top_5_recall_all",
        "mean_mode_top_5_recall_covered",
        "mean_mode_top_10_recall_all",
        "mean_mode_top_10_recall_covered",
        "mean_mode_top_20_recall_all",
        "mean_mode_top_20_recall_covered",
    ]

    print()
    print("Benchmark summary")
    print("=" * 72)

    printed_metrics: set[str] = set()

    for metric in preferred_metrics:
        if metric not in summary:
            continue

        print(f"{metric:42s} {summary[metric]}")
        printed_metrics.add(metric)

    remaining_metrics = [
        metric
        for metric in summary
        if metric not in printed_metrics
    ]

    if remaining_metrics:
        print()
        print("Additional metrics")
        print("-" * 72)

        for metric in remaining_metrics:
            print(f"{metric:42s} {summary[metric]}")


def print_intent_metrics(intent_metrics: pd.DataFrame) -> None:
    """
    Print the main intent-specific metrics.
    """
    preferred_columns = [
        "intent",
        "expected_target_count",
        "covered_target_count",
        "coverage",
        "primary_intent_accuracy",
        "acceptable_intent_accuracy",
        "cross_intent_specificity",
        "mean_reciprocal_rank_all",
        "mean_rank_covered",
        "mean_rank_shift_covered",
        "top_5_recall_all",
        "top_10_recall_all",
        "top_20_recall_all",
    ]

    available_columns = [
        column
        for column in preferred_columns
        if column in intent_metrics.columns
    ]

    print()
    print("Intent-specific metrics")
    print("=" * 72)

    print(
        intent_metrics[
            available_columns
        ].to_string(index=False)
    )


def print_missing_targets(predictions: pd.DataFrame) -> None:
    """
    Print benchmark targets absent from the ranked target table.
    """
    missing = predictions[
        ~predictions["prediction_available"]
    ].copy()

    print()
    print("Missing benchmark targets")
    print("=" * 72)

    if missing.empty:
        print("None")
        return

    columns = [
        "target_symbol",
        "benchmark_group",
        "expected_role",
        "expected_primary_intent",
    ]

    print(
        missing[columns]
        .sort_values(
            by=[
                "expected_primary_intent",
                "benchmark_group",
                "target_symbol",
            ]
        )
        .to_string(index=False)
    )


def print_prediction_errors(predictions: pd.DataFrame) -> None:
    """
    Print incorrect role and primary-intent predictions.
    """
    covered = predictions[
        predictions["prediction_available"]
    ].copy()

    role_errors = covered[
        ~covered["role_correct"]
    ].copy()

    intent_errors = covered[
        ~covered["primary_intent_correct"]
    ].copy()

    print()
    print("Role-classification errors")
    print("=" * 72)

    if role_errors.empty:
        print("None")
    else:
        print(
            role_errors[
                [
                    "target_symbol",
                    "benchmark_group",
                    "expected_role",
                    "predicted_role",
                    "expected_primary_intent",
                ]
            ]
            .sort_values(
                by=[
                    "benchmark_group",
                    "target_symbol",
                ]
            )
            .to_string(index=False)
        )

    print()
    print("Primary-intent errors")
    print("=" * 72)

    if intent_errors.empty:
        print("None")
    else:
        print(
            intent_errors[
                [
                    "target_symbol",
                    "benchmark_group",
                    "expected_primary_intent",
                    "predicted_primary_intent",
                    "predicted_primary_intent_score",
                    "acceptable_intent_correct",
                ]
            ]
            .sort_values(
                by=[
                    "expected_primary_intent",
                    "benchmark_group",
                    "target_symbol",
                ]
            )
            .to_string(index=False)
        )


def main() -> None:
    """
    Run the benchmark CLI.
    """
    args = parse_args()
    validate_args(args)

    ranked_df = load_or_build_ranked_targets(
        input_path=args.input,
        page_size=args.page_size,
        max_pages=args.max_pages,
        refresh=args.refresh,
        rebuild=args.rebuild,
    )

    print()
    print(f"Benchmark configuration: {args.config}")
    print(
        "Not-prioritized threshold: "
        f"{args.not_prioritized_threshold:.3f}"
    )

    evaluation = evaluate_benchmark(
        ranked_df=ranked_df,
        config_path=args.config,
        not_prioritized_threshold=(
            args.not_prioritized_threshold
        ),
    )

    written_paths = save_benchmark_results(
        evaluation=evaluation,
        output_dir=args.outdir,
    )

    print_summary(evaluation.summary)
    print_intent_metrics(evaluation.intent_metrics)

    if args.show_missing:
        print_missing_targets(evaluation.predictions)
    else:
        missing_count = int(
            (~evaluation.predictions["prediction_available"]).sum()
        )

        print()
        print(
            f"Missing benchmark targets: {missing_count}. "
            "Use --show-missing to display them."
        )

    if args.show_errors:
        print_prediction_errors(evaluation.predictions)

    print()
    print("Benchmark outputs")
    print("=" * 72)

    for output_name, output_path in written_paths.items():
        print(f"{output_name:30s} {output_path}")

    print()
    print(
        "Interpretation: these metrics represent internal rule-based "
        "sanity validation, not independent clinical validation."
    )


if __name__ == "__main__":
    main()
