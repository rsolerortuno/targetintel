"""Visualizations for TargetIntel-IO weight-sensitivity analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_PROFILE_ORDER = (
    "antibody_io",
    "biomarker",
    "small_molecule",
)

DEFAULT_METRICS = (
    "minimum_spearman",
    "minimum_top_5_retention",
    "minimum_top_10_retention",
    "minimum_top_20_retention",
)

METRIC_LABELS = {
    "minimum_spearman": "Minimum\nSpearman",
    "minimum_top_5_retention": "Minimum\nTop-5 retention",
    "minimum_top_10_retention": "Minimum\nTop-10 retention",
    "minimum_top_20_retention": "Minimum\nTop-20 retention",
}

PROFILE_LABELS = {
    "antibody_io": "Antibody / IO",
    "biomarker": "Biomarker",
    "small_molecule": "Small molecule",
}


def validate_sensitivity_summary(
    summary_df: pd.DataFrame,
    profile_order: Iterable[str] = DEFAULT_PROFILE_ORDER,
    metrics: Iterable[str] = DEFAULT_METRICS,
) -> None:
    """Validate the sensitivity summary used for plotting."""
    required_columns = {
        "profile_id",
        *metrics,
    }

    missing_columns = sorted(
        required_columns - set(summary_df.columns)
    )

    if missing_columns:
        raise KeyError(
            "Sensitivity summary is missing columns: "
            f"{missing_columns}"
        )

    duplicated_profiles = (
        summary_df.loc[
            summary_df["profile_id"].duplicated(keep=False),
            "profile_id",
        ]
        .astype(str)
        .unique()
        .tolist()
    )

    if duplicated_profiles:
        raise ValueError(
            "Duplicated profiles in sensitivity summary: "
            f"{sorted(duplicated_profiles)}"
        )

    available_profiles = set(
        summary_df["profile_id"].astype(str)
    )

    missing_profiles = [
        profile
        for profile in profile_order
        if profile not in available_profiles
    ]

    if missing_profiles:
        raise ValueError(
            "Sensitivity summary is missing profiles: "
            f"{missing_profiles}"
        )

    numeric = summary_df[list(metrics)].apply(
        pd.to_numeric,
        errors="coerce",
    )

    if numeric.isna().any().any():
        invalid_columns = numeric.columns[
            numeric.isna().any()
        ].tolist()

        raise ValueError(
            "Sensitivity metrics contain missing or "
            f"non-numeric values: {invalid_columns}"
        )

    outside_range = (
        numeric.lt(0)
        | numeric.gt(1)
    )

    if outside_range.any().any():
        invalid_columns = numeric.columns[
            outside_range.any()
        ].tolist()

        raise ValueError(
            "Sensitivity stability metrics must be "
            f"between 0 and 1: {invalid_columns}"
        )


def prepare_sensitivity_matrix(
    summary_df: pd.DataFrame,
    profile_order: Iterable[str] = DEFAULT_PROFILE_ORDER,
    metrics: Iterable[str] = DEFAULT_METRICS,
) -> tuple[np.ndarray, list[str], list[str]]:
    """Prepare the ordered numerical matrix and display labels."""
    profile_order = tuple(profile_order)
    metrics = tuple(metrics)

    validate_sensitivity_summary(
        summary_df=summary_df,
        profile_order=profile_order,
        metrics=metrics,
    )

    ordered = (
        summary_df
        .set_index("profile_id")
        .loc[list(profile_order), list(metrics)]
        .apply(
            pd.to_numeric,
            errors="raise",
        )
    )

    matrix = ordered.to_numpy(
        dtype=float
    )

    profile_labels = [
        PROFILE_LABELS.get(
            profile,
            profile,
        )
        for profile in profile_order
    ]

    metric_labels = [
        METRIC_LABELS.get(
            metric,
            metric,
        )
        for metric in metrics
    ]

    return (
        matrix,
        profile_labels,
        metric_labels,
    )


def plot_sensitivity_overview(
    summary_df: pd.DataFrame,
    output_path: str | Path,
    profile_order: Iterable[str] = DEFAULT_PROFILE_ORDER,
    metrics: Iterable[str] = DEFAULT_METRICS,
    title: str = (
        "Ranking stability under one-weight-at-a-time "
        "perturbations of ±20%"
    ),
    dpi: int = 220,
) -> Path:
    """
    Plot minimum rank and top-k stability across therapeutic profiles.
    """
    output_path = Path(output_path)

    if dpi <= 0:
        raise ValueError(
            "dpi must be greater than zero"
        )

    (
        matrix,
        profile_labels,
        metric_labels,
    ) = prepare_sensitivity_matrix(
        summary_df=summary_df,
        profile_order=profile_order,
        metrics=metrics,
    )

    figure_width = max(
        8.0,
        len(metric_labels) * 2.0,
    )

    figure_height = max(
        4.2,
        len(profile_labels) * 1.25,
    )

    figure, axis = plt.subplots(
        figsize=(
            figure_width,
            figure_height,
        )
    )

    image = axis.imshow(
        matrix,
        aspect="auto",
        vmin=0.0,
        vmax=1.0,
    )

    axis.set_xticks(
        np.arange(
            len(metric_labels)
        )
    )

    axis.set_xticklabels(
        metric_labels
    )

    axis.set_yticks(
        np.arange(
            len(profile_labels)
        )
    )

    axis.set_yticklabels(
        profile_labels
    )

    axis.set_xlabel(
        "Worst-case stability metric"
    )

    axis.set_ylabel(
        "Therapeutic-intent profile"
    )

    axis.set_title(
        title,
        pad=16,
    )

    for row_index in range(
        matrix.shape[0]
    ):
        for column_index in range(
            matrix.shape[1]
        ):
            value = matrix[
                row_index,
                column_index,
            ]

            axis.text(
                column_index,
                row_index,
                f"{value:.3f}",
                ha="center",
                va="center",
            )

    colorbar = figure.colorbar(
        image,
        ax=axis,
        fraction=0.046,
        pad=0.04,
    )

    colorbar.set_label(
        "Stability (1.0 = unchanged)"
    )

    figure.text(
        0.5,
        0.015,
        (
            "Each scenario perturbs one scoring weight by −20% or +20%, "
            "followed by weight renormalization."
        ),
        ha="center",
        fontsize=9,
    )

    figure.tight_layout(
        rect=(
            0.0,
            0.055,
            1.0,
            1.0,
        )
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    figure.savefig(
        output_path,
        dpi=dpi,
        bbox_inches="tight",
    )

    plt.close(
        figure
    )

    return output_path
