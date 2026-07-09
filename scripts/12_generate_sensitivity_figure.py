#!/usr/bin/env python3

"""Generate the TargetIntel-IO weight-sensitivity summary figure."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from targetintel.sensitivity_visualization import (
    plot_sensitivity_overview,
)


DEFAULT_INPUT_PATH = Path(
    "results/sensitivity/"
    "sensitivity_summary.csv"
)

DEFAULT_OUTPUT_PATH = Path(
    "results/sensitivity/"
    "sensitivity_overview.png"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a compact visualization of "
            "TargetIntel-IO ranking stability."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Sensitivity summary CSV.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output PNG path.",
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=220,
        help="Output image resolution.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.is_file():
        raise FileNotFoundError(
            f"Sensitivity summary not found: {args.input}"
        )

    if args.dpi <= 0:
        raise ValueError(
            "--dpi must be greater than zero"
        )

    summary_df = pd.read_csv(
        args.input
    )

    output_path = plot_sensitivity_overview(
        summary_df=summary_df,
        output_path=args.output,
        dpi=args.dpi,
    )

    print(
        f"Saved sensitivity figure to: {output_path}"
    )


if __name__ == "__main__":
    main()
