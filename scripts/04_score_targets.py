#!/usr/bin/env python3

"""
Score and rank TargetIntel-IO targets across therapeutic-intent profiles.

This script builds the feature table, applies all scoring profiles, ranks
targets by therapeutic intent, and saves the final ranked target table.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from targetintel.feature_table import build_feature_table
from targetintel.intent_ranking import build_intent_rankings, save_ranked_targets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score and rank TargetIntel-IO targets."
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Number of Open Targets API records per page.",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum number of Open Targets API pages to fetch.",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh cached Open Targets API data.",
    )

    parser.add_argument(
        "--out",
        type=Path,
        default=Path("results/ranked_targets.csv"),
        help="Output ranked targets CSV path.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    feature_df = build_feature_table(
        page_size=args.page_size,
        max_pages=args.max_pages,
        refresh=args.refresh,
    )

    ranked_df = build_intent_rankings(feature_df)

    output_path = save_ranked_targets(ranked_df, args.out)

    print(f"Saved ranked targets to: {output_path}")
    print(f"Rows: {len(ranked_df)}")
    print(f"Columns: {len(ranked_df.columns)}")

    preview_columns = [
        "target_symbol",
        "opentargets_rank",
        "role_classification",
        "best_modality",
        "antibody_io_final_score",
        "antibody_io_rank",
        "biomarker_final_score",
        "biomarker_rank",
        "small_molecule_final_score",
        "small_molecule_rank",
    ]

    available_columns = [
        column for column in preview_columns if column in ranked_df.columns
    ]

    print()
    print(ranked_df[available_columns].head(30).to_string(index=False))


if __name__ == "__main__":
    main()
