"""
Target-universe construction utilities for TargetIntel-IO.

This module augments an Open Targets-derived dataframe with required target
symbols that were not retrieved in the selected Open Targets top-N results.

This is useful for benchmark evaluation, where all curated benchmark targets
must pass through the TargetIntel-IO classification and scoring pipeline.

Added targets are explicitly marked as lacking retrieved Open Targets evidence.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd


OPEN_TARGETS_SOURCE = "opentargets"
REQUIRED_SYMBOL_SOURCE = "required_symbol"


def _normalize_symbol(value: Any) -> str:
    """Normalize a target symbol for matching."""
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return str(value).strip().upper()


def _normalize_required_symbols(
    required_symbols: Iterable[str] | None,
) -> list[str]:
    """Normalize, deduplicate, and sort required target symbols."""
    if required_symbols is None:
        return []

    symbols = {
        _normalize_symbol(symbol)
        for symbol in required_symbols
        if _normalize_symbol(symbol)
    }

    return sorted(symbols)


def _first_non_missing(
    series: pd.Series,
    default: Any = pd.NA,
) -> Any:
    """Return the first non-missing value in a pandas Series."""
    for value in series:
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass

        return value

    return default


def augment_target_universe(
    target_df: pd.DataFrame,
    required_symbols: Iterable[str] | None,
) -> pd.DataFrame:
    """
    Add required targets absent from the Open Targets-derived dataframe.

    Parameters
    ----------
    target_df:
        Dataframe produced from Open Targets.
    required_symbols:
        Target symbols that must be represented in the downstream pipeline.

    Returns
    -------
    pandas.DataFrame
        Original targets plus explicitly marked required-symbol rows.

    Notes
    -----
    Added targets receive:

    - opentargets_score = 0.0
    - opentargets_evidence_available = False
    - target_universe_source = "required_symbol"
    - missing Open Targets target identifiers and metadata

    Retrieved Open Targets targets receive:

    - opentargets_evidence_available = True
    - target_universe_source = "opentargets"
    """
    if "target_symbol" not in target_df.columns:
        raise KeyError(
            "Target dataframe must contain a 'target_symbol' column."
        )

    required = _normalize_required_symbols(required_symbols)

    df = target_df.copy()

    df["target_symbol"] = df["target_symbol"].map(_normalize_symbol)

    if "opentargets_score" not in df.columns:
        df["opentargets_score"] = pd.NA

    df["opentargets_score"] = pd.to_numeric(
        df["opentargets_score"],
        errors="coerce",
    )

    if "opentargets_evidence_available" not in df.columns:
        df["opentargets_evidence_available"] = (
            df["opentargets_score"].notna()
        )
    else:
        df["opentargets_evidence_available"] = (
            df["opentargets_evidence_available"]
            .fillna(False)
            .astype(bool)
        )

    if "target_universe_source" not in df.columns:
        df["target_universe_source"] = OPEN_TARGETS_SOURCE
    else:
        df["target_universe_source"] = (
            df["target_universe_source"]
            .fillna(OPEN_TARGETS_SOURCE)
            .astype(str)
        )

    existing_symbols = {
        symbol
        for symbol in df["target_symbol"]
        if symbol
    }

    missing_symbols = [
        symbol
        for symbol in required
        if symbol not in existing_symbols
    ]

    if not missing_symbols:
        return df.reset_index(drop=True)

    disease_id = (
        _first_non_missing(df["disease_id"])
        if "disease_id" in df.columns
        else pd.NA
    )

    disease_name = (
        _first_non_missing(df["disease_name"])
        if "disease_name" in df.columns
        else pd.NA
    )

    added_records: list[dict[str, Any]] = []

    for symbol in missing_symbols:
        record: dict[str, Any] = {
            column: pd.NA
            for column in df.columns
        }

        record.update(
            {
                "target_symbol": symbol,
                "target_id": pd.NA,
                "target_name": pd.NA,
                "biotype": pd.NA,
                "disease_id": disease_id,
                "disease_name": disease_name,
                "opentargets_score": 0.0,
                "datatype_scores": {},
                "datasource_scores": {},
                "opentargets_evidence_available": False,
                "target_universe_source": REQUIRED_SYMBOL_SOURCE,
            }
        )

        added_records.append(record)

    added_df = pd.DataFrame(added_records)

    augmented_df = pd.concat(
        [df, added_df],
        ignore_index=True,
        sort=False,
    )

    augmented_df["_source_order"] = (
        augmented_df["opentargets_evidence_available"]
        .fillna(False)
        .astype(bool)
        .map({True: 0, False: 1})
    )

    augmented_df = augmented_df.sort_values(
        by=[
            "_source_order",
            "opentargets_score",
            "target_symbol",
        ],
        ascending=[
            True,
            False,
            True,
        ],
        na_position="last",
    )

    augmented_df = augmented_df.drop(
        columns="_source_order"
    ).reset_index(drop=True)

    return augmented_df
