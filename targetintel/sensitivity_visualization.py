"""Visualizations for TargetIntel-IO weight-sensitivity analysis."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

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
    "minimum_spearman": "Minimum Spearman",
    "minimum_top_5_retention": "Top-5 retention",
    "minimum_top_10_retention": "Top-10 retention",
    "minimum_top_20_retention": "Top-20 retention",
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
    profile_order = tuple(profile_order)
    metrics = tuple(metrics)

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
        profile_id
        for profile_id in profile_order
        if profile_id not in available_profiles
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

    outside_range = numeric.lt(0) | numeric.gt(1)

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
            profile_id,
            profile_id,
        )
        for profile_id in profile_order
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


def _heatmap_limits(
    matrix: np.ndarray,
) -> tuple[float, float]:
    """
    Choose a compact heatmap scale so differences near 1.0 remain visible.
    """
    min_value = float(np.nanmin(matrix))
    lower = min(0.90, np.floor((min_value - 0.03) * 100) / 100)

    lower = max(0.0, lower)
    upper = 1.0

    if lower >= upper:
        lower = max(0.0, upper - 0.10)

    return lower, upper


def plot_sensitivity_overview(
    summary_df: pd.DataFrame,
    output_path: str | Path,
    profile_order: Iterable[str] = DEFAULT_PROFILE_ORDER,
    metrics: Iterable[str] = DEFAULT_METRICS,
    title: str = (
        "Worst-case ranking stability under "
        "±20% scoring-weight perturbations"
    ),
    dpi: int = 220,
) -> Path:
    """
    Plot worst-case ranking stability as a compact heatmap.
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

    vmin, vmax = _heatmap_limits(matrix)

    figure, axis = plt.subplots(
        figsize=(9.8, 4.8)
    )

    image = axis.imshow(
        matrix,
        aspect="auto",
        vmin=vmin,
        vmax=vmax,
        interpolation="nearest",
    )

    axis.set_xticks(
        np.arange(len(metric_labels))
    )
    axis.set_xticklabels(
        metric_labels,
        rotation=20,
        ha="right",
    )

    axis.set_yticks(
        np.arange(len(profile_labels))
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
        pad=14,
    )

    axis.set_xticks(
        np.arange(-0.5, len(metric_labels), 1),
        minor=True,
    )
    axis.set_yticks(
        np.arange(-0.5, len(profile_labels), 1),
        minor=True,
    )
    axis.grid(
        which="minor",
        color="white",
        linestyle="-",
        linewidth=1.2,
    )
    axis.tick_params(
        which="minor",
        bottom=False,
        left=False,
    )

    midpoint = (vmin + vmax) / 2

    for row_index in range(matrix.shape[0]):
        for column_index in range(matrix.shape[1]):
            value = matrix[row_index, column_index]

            text_color = (
                "white"
                if value < midpoint
                else "black"
            )

            axis.text(
                column_index,
                row_index,
                f"{value:.3f}",
                ha="center",
                va="center",
                color=text_color,
                fontsize=10,
                fontweight="bold",
            )

    colorbar = figure.colorbar(
        image,
        ax=axis,
        fraction=0.046,
        pad=0.04,
    )
    colorbar.set_label(
        "Worst-case stability (1.0 = unchanged)"
    )

    figure.text(
        0.5,
        0.02,
        (
            "Each scenario changes one scoring weight by −20% or +20%, "
            "then renormalizes all weights. "
            "The heatmap shows the minimum value observed for each metric."
        ),
        ha="center",
        fontsize=9,
    )

    figure.tight_layout(
        rect=(
            0.0,
            0.06,
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

    plt.close(figure)

    return output_path
