"""Command-line interface for TargetIntel-IO."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from targetintel.pipeline import (
    PipelineOutputs,
    run_pipeline,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the TargetIntel-IO command-line parser."""
    parser = argparse.ArgumentParser(
        prog="targetintel",
        description=(
            "Explainable therapeutic-intent-aware target triage "
            "for anti-PD-1-resistant melanoma."
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    run_parser = subparsers.add_parser(
        "run",
        help=(
            "Run the TargetIntel-IO workflow from public-data "
            "ingestion to ranked targets and reports."
        ),
    )

    run_parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="Number of Open Targets records per API page.",
    )

    run_parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Maximum number of Open Targets pages to retrieve.",
    )

    run_parser.add_argument(
        "--top-n-per-mode",
        type=int,
        default=10,
        help=(
            "Number of top targets per therapeutic-intent mode "
            "used for cards, reports, and figures."
        ),
    )

    run_parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore cached Open Targets data and query the API again.",
    )

    run_parser.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Also run the 56-target benchmark and the 42-scenario "
            "weight-sensitivity analysis."
        ),
    )

    run_parser.add_argument(
        "--evidence-store",
        type=Path,
        default=None,
        help=(
            "Optional local immutable evidence DuckDB store used only to "
            "decorate reports after deterministic ranking."
        ),
    )

    return parser


def _display_outputs(
    outputs: PipelineOutputs,
) -> None:
    """Print a concise output summary."""
    print()
    print("=" * 78)
    print("TargetIntel-IO completed successfully")
    print("=" * 78)

    output_rows: list[
        tuple[str, Path | None]
    ] = [
        (
            "Feature table",
            outputs.feature_table,
        ),
        (
            "Ranked targets",
            outputs.ranked_targets,
        ),
        (
            "Target cards",
            outputs.target_cards_dir,
        ),
        (
            "HTML reports",
            outputs.html_reports_dir,
        ),
        (
            "Figures",
            outputs.figures_dir,
        ),
        (
            "Benchmark",
            outputs.benchmark_dir,
        ),
        (
            "Sensitivity",
            outputs.sensitivity_dir,
        ),
    ]

    for label, path in output_rows:
        if path is not None:
            print(
                f"{label:16s} {path}"
            )

    print()
    print(
        "Open the report index at:"
    )
    print(
        outputs.html_reports_dir
        / "index.html"
    )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run the TargetIntel-IO command-line interface."""
    parser = build_parser()
    args = parser.parse_args(
        argv
    )

    if args.command != "run":
        parser.error(
            f"Unsupported command: {args.command}"
        )

    pipeline_kwargs = dict(
        page_size=args.page_size,
        max_pages=args.max_pages,
        refresh=args.refresh,
        top_n_per_mode=args.top_n_per_mode,
        validate=args.validate,
    )
    if args.evidence_store is not None:
        pipeline_kwargs["evidence_store_path"] = args.evidence_store
    outputs = run_pipeline(
        **pipeline_kwargs,
    )

    _display_outputs(
        outputs
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
