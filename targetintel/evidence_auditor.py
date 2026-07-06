"""
Evidence-for / evidence-against auditor for TargetIntel-IO.

This module generates transparent supporting and opposing evidence statements
for each candidate target.

The goal is not to prove causality, but to make target triage more realistic:
a target may be biologically relevant while still being a poor direct
therapeutic candidate for a given modality.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class EvidenceCall:
    """Container for evidence-auditor output."""

    evidence_for: str
    evidence_against: str
    contradiction_score: float
    main_limitation: str
    deprioritization_reason: str


def _as_bool(value: Any) -> bool:
    """Robustly convert common values to bool."""
    if isinstance(value, bool):
        return value

    if pd.isna(value):
        return False

    value_str = str(value).strip().lower()

    return value_str in {"true", "1", "yes", "y"}


def _safe_str(value: Any) -> str:
    """Convert missing values to empty strings."""
    if pd.isna(value):
        return ""

    return str(value)


def _split_evidence(value: Any) -> list[str]:
    """
    Split evidence strings produced by previous modules.

    Existing ontology evidence uses ' | ' as separator.
    """
    value = _safe_str(value)

    if not value:
        return []

    return [item.strip() for item in value.split("|") if item.strip()]


def _join_unique(items: list[str]) -> str:
    """Join unique evidence statements while preserving order."""
    seen = set()
    unique_items = []

    for item in items:
        if item and item not in seen:
            unique_items.append(item)
            seen.add(item)

    return " | ".join(unique_items)


def audit_evidence_for_gene(row: pd.Series) -> EvidenceCall:
    """
    Generate evidence-for and evidence-against statements for one target.

    Parameters
    ----------
    row:
        Row from the TargetIntel-IO feature table.

    Returns
    -------
    EvidenceCall
        Evidence-for, evidence-against, contradiction score, main limitation,
        and deprioritization reason.
    """
    symbol = _safe_str(row.get("target_symbol", "unknown"))
    opentargets_score = row.get("opentargets_score", None)
    resistance_axis = _safe_str(row.get("resistance_axis", "unmapped"))
    matched_programs = _safe_str(row.get("matched_resistance_programs", ""))
    role = _safe_str(row.get("role_classification", ""))
    role_confidence = _safe_str(row.get("role_confidence", ""))
    therapeutic_direction = _safe_str(row.get("therapeutic_direction", ""))
    best_modality = _safe_str(row.get("best_modality", ""))
    antibody_fit = _safe_str(row.get("antibody_fit", ""))
    small_molecule_fit = _safe_str(row.get("small_molecule_fit", ""))
    biomarker_fit = _safe_str(row.get("biomarker_fit", ""))
    io_combination_fit = _safe_str(row.get("io_combination_fit", ""))
    poor_direct_target_flag = _as_bool(row.get("poor_direct_target_flag", False))

    evidence_for: list[str] = []
    evidence_against: list[str] = []

    # Start from curated ontology statements.
    evidence_for.extend(_split_evidence(row.get("axis_evidence_for", "")))
    evidence_against.extend(_split_evidence(row.get("axis_evidence_against", "")))

    # Disease-association evidence.
    if pd.notna(opentargets_score):
        try:
            score_float = float(opentargets_score)

            if score_float >= 0.7:
                evidence_for.append(
                    f"High Open Targets melanoma association score ({score_float:.3f})"
                )
            elif score_float >= 0.4:
                evidence_for.append(
                    f"Moderate Open Targets melanoma association score ({score_float:.3f})"
                )
            else:
                evidence_against.append(
                    f"Low Open Targets melanoma association score ({score_float:.3f})"
                )
        except (TypeError, ValueError):
            evidence_against.append("Open Targets association score could not be parsed")
    else:
        evidence_against.append("Missing Open Targets melanoma association score")

    # Resistance-axis relevance.
    if resistance_axis and resistance_axis != "unmapped":
        evidence_for.append(
            f"Maps to curated anti-PD-1 resistance program: {matched_programs}"
        )
    else:
        evidence_against.append(
            "Not currently mapped to a curated anti-PD-1 resistance axis"
        )

    # Role-confidence evidence.
    if role_confidence in {"high", "medium-high"}:
        evidence_for.append(f"Stable role classifier confidence is {role_confidence}")
    elif role_confidence in {"low", "none"}:
        evidence_against.append(f"Stable role classifier confidence is {role_confidence}")

    # Modality evidence.
    if antibody_fit in {"high", "medium-high"}:
        evidence_for.append(f"Antibody fit is {antibody_fit}")

    if small_molecule_fit in {"high", "medium-high"}:
        evidence_for.append(f"Small-molecule fit is {small_molecule_fit}")

    if biomarker_fit in {"high", "medium-high"}:
        evidence_for.append(f"Biomarker fit is {biomarker_fit}")

    if io_combination_fit in {"high", "medium-high"}:
        evidence_for.append(f"IO-combination fit is {io_combination_fit}")

    if antibody_fit in {"low", "unclear"} and "antibody" in best_modality.lower():
        evidence_against.append(
            "Best modality suggests antibody use, but antibody fit is weak or unclear"
        )

    if poor_direct_target_flag:
        evidence_against.append(
            "Flagged as poor direct therapeutic target for this MVP"
        )

    # Role-specific opposing evidence.
    role_lower = role.lower()

    if "poor direct therapeutic target" in role_lower:
        evidence_against.append(
            "Role classifier indicates biological relevance but poor direct targetability"
        )

    if "biomarker" in role_lower and "target" not in role_lower:
        evidence_against.append(
            "Most useful as biomarker or stratification marker rather than direct therapeutic target"
        )

    if "immune-context marker" in role_lower:
        evidence_against.append(
            "May reflect immune-cell abundance rather than causal target biology"
        )

    if "tumor-intrinsic driver" in role_lower and antibody_fit == "low":
        evidence_against.append(
            "Tumor-intrinsic role and low antibody fit argue against antibody/IO-combination prioritization"
        )

    if "checkpoint" in resistance_axis and io_combination_fit in {"high", "medium-high"}:
        evidence_for.append(
            "Checkpoint-axis biology supports anti-PD-1 combination rationale"
        )

    if "myeloid" in resistance_axis and io_combination_fit in {"medium-high", "high"}:
        evidence_for.append(
            "Myeloid/TME biology supports anti-PD-1 combination hypothesis"
        )

    # Contradiction score.
    contradiction_score = calculate_contradiction_score(
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        poor_direct_target_flag=poor_direct_target_flag,
        antibody_fit=antibody_fit,
        small_molecule_fit=small_molecule_fit,
        biomarker_fit=biomarker_fit,
        io_combination_fit=io_combination_fit,
        role=role,
    )

    main_limitation = infer_main_limitation(
        role=role,
        resistance_axis=resistance_axis,
        poor_direct_target_flag=poor_direct_target_flag,
        antibody_fit=antibody_fit,
        small_molecule_fit=small_molecule_fit,
        biomarker_fit=biomarker_fit,
        io_combination_fit=io_combination_fit,
    )

    deprioritization_reason = infer_deprioritization_reason(
        symbol=symbol,
        role=role,
        resistance_axis=resistance_axis,
        poor_direct_target_flag=poor_direct_target_flag,
        antibody_fit=antibody_fit,
        small_molecule_fit=small_molecule_fit,
        biomarker_fit=biomarker_fit,
        io_combination_fit=io_combination_fit,
        therapeutic_direction=therapeutic_direction,
    )

    return EvidenceCall(
        evidence_for=_join_unique(evidence_for),
        evidence_against=_join_unique(evidence_against),
        contradiction_score=contradiction_score,
        main_limitation=main_limitation,
        deprioritization_reason=deprioritization_reason,
    )


def calculate_contradiction_score(
    evidence_for: list[str],
    evidence_against: list[str],
    poor_direct_target_flag: bool,
    antibody_fit: str,
    small_molecule_fit: str,
    biomarker_fit: str,
    io_combination_fit: str,
    role: str,
) -> float:
    """
    Calculate a simple contradiction score.

    Higher values mean the target has more reasons to be interpreted cautiously.
    This is not a statistical score. It is a transparent heuristic for triage.
    """
    score = 0.0

    if evidence_against:
        score += min(0.4, 0.08 * len(evidence_against))

    if poor_direct_target_flag:
        score += 0.25

    role_lower = role.lower()

    if "biomarker" in role_lower and io_combination_fit in {"high", "medium-high"}:
        score += 0.10

    if "tumor-intrinsic driver" in role_lower and antibody_fit == "high":
        score += 0.15

    if antibody_fit == "low" and io_combination_fit == "high":
        score += 0.15

    if (
        antibody_fit in {"low", "unclear"}
        and small_molecule_fit in {"low", "unclear"}
        and biomarker_fit in {"low", "unclear"}
        and io_combination_fit in {"low", "unclear"}
    ):
        score += 0.20

    return round(min(score, 1.0), 3)


def infer_main_limitation(
    role: str,
    resistance_axis: str,
    poor_direct_target_flag: bool,
    antibody_fit: str,
    small_molecule_fit: str,
    biomarker_fit: str,
    io_combination_fit: str,
) -> str:
    """
    Infer the main limitation for a candidate target.
    """
    role_lower = role.lower()

    if poor_direct_target_flag:
        return "Poor direct therapeutic target despite biological relevance"

    if resistance_axis == "unmapped":
        return "No curated anti-PD-1 resistance-axis mapping"

    if "biomarker" in role_lower:
        return "Likely more useful for stratification than direct therapeutic targeting"

    if "immune-context marker" in role_lower:
        return "May reflect immune context rather than causal target biology"

    if "tumor-intrinsic driver" in role_lower and antibody_fit == "low":
        return "Poor fit for antibody / IO-combination modality"

    if antibody_fit == "unclear" and small_molecule_fit == "unclear":
        return "Therapeutic modality fit is unclear"

    if io_combination_fit == "low" and "anti-PD-1" in role_lower:
        return "Weak IO-combination modality fit despite role annotation"

    return "No major limitation flagged by current MVP rules"


def infer_deprioritization_reason(
    symbol: str,
    role: str,
    resistance_axis: str,
    poor_direct_target_flag: bool,
    antibody_fit: str,
    small_molecule_fit: str,
    biomarker_fit: str,
    io_combination_fit: str,
    therapeutic_direction: str,
) -> str:
    """
    Infer why a target might be deprioritized in a target-ID discussion.
    """
    role_lower = role.lower()

    if poor_direct_target_flag:
        return (
            f"{symbol} should be deprioritized as a direct therapeutic target "
            "in this MVP, but may remain useful as biomarker or pathway context."
        )

    if resistance_axis == "unmapped":
        return (
            f"{symbol} lacks current curated anti-PD-1 resistance-axis support "
            "in TargetIntel-IO."
        )

    if "biomarker" in role_lower and biomarker_fit in {"high", "medium-high"}:
        return (
            f"{symbol} should not be deprioritized globally, but should be ranked "
            "mainly in biomarker or patient-stratification mode."
        )

    if "tumor-intrinsic driver" in role_lower and io_combination_fit == "low":
        return (
            f"{symbol} should be deprioritized in antibody/IO-combination mode "
            "and evaluated instead in tumor-intrinsic or small-molecule mode."
        )

    if antibody_fit == "low" and "block" in therapeutic_direction.lower():
        return (
            f"{symbol} has blockade-like directionality but weak antibody fit in "
            "the current MVP rules."
        )

    return "No strong deprioritization reason from current MVP rules"


def audit_evidence_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add evidence-for / evidence-against annotations to a dataframe.

    Parameters
    ----------
    df:
        TargetIntel-IO feature table after role and modality annotation.

    Returns
    -------
    pandas.DataFrame
        Input dataframe with evidence-auditor columns appended.
    """
    df = df.copy()

    calls = []

    for _, row in df.iterrows():
        call = audit_evidence_for_gene(row)
        calls.append(call.__dict__)

    calls_df = pd.DataFrame(calls)

    for column in calls_df.columns:
        df[column] = calls_df[column]

    return df
