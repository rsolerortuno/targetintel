"""Tests for sensitivity-analysis visualizations."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from targetintel.sensitivity_visualization import (
    plot_sensitivity_overview,
    prepare_sensitivity_matrix,
    validate_sensitivity_summary,
)


def _summary_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "profile_id": [
                "antibody_io",
                "biomarker",
                "small_molecule",
            ],
            "minimum_spearman": [
                0.9999,
                0.9998,
                0.9852,
            ],
            "minimum_top_5_retention": [
                1.0,
                1.0,
                1.0,
            ],
            "minimum_top_10_retention": [
                0.9,
                1.0,
                0.9,
            ],
            "minimum_top_20_retention": [
                1.0,
                0.95,
                1.0,
            ],
        }
    )


def test_validate_sensitivity_summary_accepts_valid_data() -> None:
    validate_sensitivity_summary(
        _summary_dataframe()
    )


def test_prepare_sensitivity_matrix_preserves_profile_order() -> None:
    shuffled = (
        _summary_dataframe()
        .sample(
            frac=1.0,
            random_state=1,
        )
        .reset_index(drop=True)
    )

    (
        matrix,
        profile_labels,
        metric_labels,
    ) = prepare_sensitivity_matrix(
        shuffled
    )

    assert matrix.shape == (
        3,
        4,
    )

    assert profile_labels == [
        "Antibody / IO",
        "Biomarker",
        "Small molecule",
    ]

    assert metric_labels == [
        "Minimum Spearman",
        "Top-5 retention",
        "Top-10 retention",
        "Top-20 retention",
    ]

    assert matrix[0, 0] == pytest.approx(
        0.9999
    )

    assert matrix[2, 2] == pytest.approx(
        0.9
    )


def test_validation_rejects_missing_metric() -> None:
    invalid = _summary_dataframe().drop(
        columns="minimum_spearman"
    )

    with pytest.raises(
        KeyError,
        match="missing columns",
    ):
        validate_sensitivity_summary(
            invalid
        )


def test_validation_rejects_out_of_range_metric() -> None:
    invalid = _summary_dataframe()

    invalid.loc[
        0,
        "minimum_top_10_retention",
    ] = 1.2

    with pytest.raises(
        ValueError,
        match="between 0 and 1",
    ):
        validate_sensitivity_summary(
            invalid
        )


def test_plot_sensitivity_overview_creates_png(
    tmp_path: Path,
) -> None:
    output_path = (
        tmp_path
        / "sensitivity_overview.png"
    )

    result = plot_sensitivity_overview(
        summary_df=_summary_dataframe(),
        output_path=output_path,
        dpi=100,
    )

    assert result == output_path
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
