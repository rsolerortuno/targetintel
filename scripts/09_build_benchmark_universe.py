#!/usr/bin/env python3

"""
Build a complete TargetIntel-IO benchmark target universe.

The output contains:

- the selected top-N Open Targets melanoma-associated targets;
- every target defined in the curated benchmark configuration.

Benchmark targets absent from the Open Targets top-N are added with:

- opentargets_score = 0.0
- opentargets_evidence_available = False
- opentargets_rank = missing

This separates Open Targets retrieval coverage from TargetIntel-IO rule and
therapeutic-intent evaluation coverage.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from targetintel.benchmark import (
    DEFAULT_BENCHMARK_CONFIG_PATH,
    benchmark_config_to_dataframe,
    load_benchmark_config,
)
from targetintel.feature_table import build_feature_table
from targetintel.intent_ranking import (
    build_intent_rankings,
    save_ranked_targets,
)


DEFAULT_OUTPUT_PATH = Path(
    "results/benchmark/ranked_targets_benchmark_universe.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the augmented TargetIntel-IO benchmark universe."
        )
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_BENCHMARK_CONFIG_PATH,
        help="Benchmark YAML configuration.",
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output ranked-target CSV.",
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Number of Open Targets records per API page.",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum Open Targets API pages.",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh cached Open Targets data.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    benchmark_config = load_benchmark_config(
        args.config
    )

    benchmark_reference = benchmark_config_to_dataframe(
        benchmark_config
    )

    benchmark_symbols = sorted(
        benchmark_reference["target_symbol"]
        .dropna()
        .astype(str)
        .str.upper()
        .unique()
        .tolist()
    )

    print(
        f"Benchmark targets required: {len(benchmark_symbols)}"
    )

    feature_df = build_feature_table(
        page_size=args.page_size,
        max_pages=args.max_pages,
        refresh=args.refresh,
        required_symbols=benchmark_symbols,
    )

    ranked_df = build_intent_rankings(feature_df)

    ranked_symbols = set(
        ranked_df["target_symbol"]
        .dropna()
        .astype(str)
        .str.upper()
    )

    missing_after_augmentation = sorted(
        set(benchmark_symbols) - ranked_symbols
    )

    if missing_after_augmentation:
        raise RuntimeError(
            "Benchmark targets remain missing after augmentation: "
            f"{missing_after_augmentation}"
        )

    evidence_available = (
        ranked_df["opentargets_evidence_available"]
        .fillna(False)
        .astype(bool)
    )

    source_counts = (
        ranked_df["target_universe_source"]
        .fillna("unknown")
        .value_counts()
    )

    output_path = save_ranked_targets(
        ranked_df,
        output_path=args.out,
    )

    benchmark_rows = ranked_df[
        ranked_df["target_symbol"].isin(
            benchmark_symbols
        )
    ]

    benchmark_retrieved_count = int(
        benchmark_rows[
            "opentargets_evidence_available"
        ]
        .fillna(False)
        .astype(bool)
        .sum()
    )

    print()
    print(f"Saved benchmark universe to: {output_path}")
    print(f"Total target-universe rows: {len(ranked_df)}")
    print(
        "Open Targets retrieved rows: "
        f"{int(evidence_available.sum())}"
    )
    print(
        "Required-symbol rows added: "
        f"{int((~evidence_available).sum())}"
    )
    print(
        "Benchmark targets retrieved by Open Targets: "
        f"{benchmark_retrieved_count}/{len(benchmark_symbols)}"
    )
    print(
        "Benchmark targets evaluable by TargetIntel-IO: "
        f"{len(benchmark_rows)}/{len(benchmark_symbols)}"
    )

    print()
    print("Target-universe source counts:")
    print(source_counts.to_string())


if __name__ == "__main__":
    main()
