"""
Confidence and uncertainty scoring for TargetIntel-IO.

This module estimates how complete and reliable the current evidence is for
each candidate target. The goal is not to prove biological validity, but to
make the triage output honest about missing evidence and uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ConfidenceCall:
    """Container for confidence and uncertainty output."""

    data_completeness_score: float
    missing_evidence_fields: str
    confidence_level: str
    uncertainty_reason: str


REQUIRED_EVIDENCE_FIELDS = [
    "opentargets_score",
    "resistance_axis",
    "role_classification",
    "role_confidence",
    "therapeutic_direction",
    "best_modality",
    "evidence_for",
    "evidence_against",
    "main_limitation",
]


def _is_missing(value: Any) -> bool:
    """Return True if a value should count as missing or uninformative."""
    if value is None:
        return True

    if isinstance(value, float) and pd.isna(value):
        return True

    value_str = str(value).strip().lower()

    return value_str in {
        "",
        "nan",
        "none",
        "null",
        "unclear",
        "unmapped",
        "not assessed",
    }


def _safe_str(value: Any) -> str:
    """Convert missing values to safe strings."""
    if value is None:
        return ""

    if isinstance(value, float) and pd.isna(value):
        return ""

    return str(value)


def score_data_completeness(row: pd.Series) -> tuple[float, list[str]]:
    """
    Score how many required evidence fields are present.

    Returns
    -------
    tuple
        Completeness score from 0 to 1 and list of missing fields.
    """
    missing_fields = []

    for field in REQUIRED_EVIDENCE_FIELDS:
        if field not in row.index or _is_missing(row.get(field)):
            missing_fields.append(field)

    present_count = len(REQUIRED_EVIDENCE_FIELDS) - len(missing_fields)
    completeness_score = present_count / len(REQUIRED_EVIDENCE_FIELDS)

    return round(completeness_score, 3), missing_fields


def assign_confidence_level(
    row: pd.Series,
    data_completeness_score: float,
    missing_fields: list[str],
) -> str:
    """
    Assign high / medium / low / insufficient confidence.
    """
    role_confidence = _safe_str(row.get("role_confidence")).lower()
    resistance_axis = _safe_str(row.get("resistance_axis")).lower()
    evidence_for = _safe_str(row.get("evidence_for"))
    evidence_against = _safe_str(row.get("evidence_against"))
    best_modality = _safe_str(row.get("best_modality")).lower()
    contradiction_score = row.get("contradiction_score", 0)

    try:
        contradiction_score = float(contradiction_score)
    except (TypeError, ValueError):
        contradiction_score = 0.0

    has_resistance_axis = resistance_axis not in {"", "unmapped", "nan"}
    has_evidence_for = bool(evidence_for.strip())
    has_evidence_against = bool(evidence_against.strip())
    has_modality = best_modality not in {"", "unclear", "nan"}

    if data_completeness_score < 0.45:
        return "insufficient evidence to classify"

    if (
        data_completeness_score >= 0.85
        and role_confidence in {"high", "medium-high"}
        and has_resistance_axis
        and has_evidence_for
        and has_evidence_against
        and has_modality
        and contradiction_score <= 0.45
    ):
        return "high confidence"

    if (
        data_completeness_score >= 0.65
        and role_confidence in {"high", "medium-high", "medium"}
        and has_evidence_for
        and has_modality
    ):
        return "medium confidence"

    if data_completeness_score >= 0.45:
        return "low confidence"

    return "insufficient evidence to classify"


def infer_uncertainty_reason(
    row: pd.Series,
    missing_fields: list[str],
    confidence_level: str,
) -> str:
    """
    Generate a concise reason explaining uncertainty.
    """
    resistance_axis = _safe_str(row.get("resistance_axis")).lower()
    role_confidence = _safe_str(row.get("role_confidence")).lower()
    best_modality = _safe_str(row.get("best_modality")).lower()
    contradiction_score = row.get("contradiction_score", 0)
    main_limitation = _safe_str(row.get("main_limitation"))

    try:
        contradiction_score = float(contradiction_score)
    except (TypeError, ValueError):
        contradiction_score = 0.0

    reasons = []

    if missing_fields:
        reasons.append(
            "Missing evidence fields: " + ", ".join(missing_fields)
        )

    if resistance_axis in {"", "unmapped", "nan"}:
        reasons.append("No curated anti-PD-1 resistance-axis mapping")

    if role_confidence in {"", "low", "none"}:
        reasons.append("Low role-classifier confidence")

    if best_modality in {"", "unclear", "nan"}:
        reasons.append("Therapeutic modality fit is unclear")

    if contradiction_score >= 0.6:
        reasons.append("High contradiction score indicates important opposing evidence")
    elif contradiction_score >= 0.4:
        reasons.append("Moderate contradiction score indicates caution is needed")

    if main_limitation:
        reasons.append(f"Main limitation: {main_limitation}")

    if not reasons and confidence_level == "high confidence":
        return "Evidence is relatively complete under current MVP rules"

    if not reasons:
        return "No specific uncertainty reason identified by current MVP rules"

    return " | ".join(reasons)


def assess_confidence_for_gene(row: pd.Series) -> ConfidenceCall:
    """
    Assess confidence and uncertainty for one target.
    """
    completeness_score, missing_fields = score_data_completeness(row)

    confidence_level = assign_confidence_level(
        row=row,
        data_completeness_score=completeness_score,
        missing_fields=missing_fields,
    )

    uncertainty_reason = infer_uncertainty_reason(
        row=row,
        missing_fields=missing_fields,
        confidence_level=confidence_level,
    )

    return ConfidenceCall(
        data_completeness_score=completeness_score,
        missing_evidence_fields="; ".join(missing_fields),
        confidence_level=confidence_level,
        uncertainty_reason=uncertainty_reason,
    )


def assess_confidence_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add confidence and uncertainty annotations to a dataframe.
    """
    df = df.copy()

    calls = []

    for _, row in df.iterrows():
        call = assess_confidence_for_gene(row)
        calls.append(call.__dict__)

    calls_df = pd.DataFrame(calls)

    for column in calls_df.columns:
        df[column] = calls_df[column]

    return df
