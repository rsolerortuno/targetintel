"""
Feature table construction for TargetIntel-IO.

This module combines:
1. Open Targets melanoma target-disease association evidence
2. Curated anti-PD-1 resistance-axis ontology annotations
3. Stable rule-based translational role classification
4. Modality-aware target reasoning
5. Evidence-for / evidence-against auditing
6. Confidence and uncertainty scoring

The resulting table is the first TargetIntel-IO feature table used by
downstream intent-aware ranking, benchmarking, target cards, and dashboard outputs.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from targetintel.confidence import assess_confidence_dataframe
from targetintel.evidence_auditor import audit_evidence_dataframe
from targetintel.modality import annotate_modality_dataframe
from targetintel.opentargets import get_melanoma_associated_targets
from targetintel.resistance_ontology import annotate_dataframe
from targetintel.role_classifier import classify_dataframe
from targetintel.target_universe import augment_target_universe


DEFAULT_FEATURE_TABLE_PATH = Path(
    "data/processed/targetintel_feature_table_v0_1.csv"
)


def build_feature_table(
    page_size: int = 100,
    max_pages: int = 3,
    refresh: bool = False,
    required_symbols: list[str] | tuple[str, ...] | set[str] | None = None,
) -> pd.DataFrame:
    """
    Build the first TargetIntel-IO feature table.

    Parameters
    ----------
    page_size:
        Number of Open Targets records per API page.
    max_pages:
        Maximum number of Open Targets pages to retrieve.
    refresh:
        If True, refresh the Open Targets cache.

    Returns
    -------
    pandas.DataFrame
        Feature table containing Open Targets association features,
        resistance-axis annotations, stable role classification,
        modality-fit annotations, evidence-for/evidence-against auditing,
        and confidence/uncertainty scoring.
    """
    opentargets_df = get_melanoma_associated_targets(
        page_size=page_size,
        max_pages=max_pages,
        refresh=refresh,
    )

    opentargets_df = augment_target_universe(
        opentargets_df,
        required_symbols=required_symbols,
    )

    feature_df = annotate_dataframe(
        opentargets_df,
        gene_column="target_symbol",
    )

    feature_df = classify_dataframe(
        feature_df,
        gene_column="target_symbol",
        resistance_axis_column="resistance_axis",
        expected_role_column="expected_role_from_axis",
    )

    feature_df = annotate_modality_dataframe(
        feature_df,
        gene_column="target_symbol",
        role_column="role_classification",
        therapeutic_direction_column="therapeutic_direction",
        resistance_axis_column="resistance_axis",
    )

    feature_df = audit_evidence_dataframe(feature_df)

    feature_df = assess_confidence_dataframe(feature_df)

    feature_df = add_initial_translational_features(feature_df)

    return feature_df


def add_initial_translational_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add simple first-pass translational features.

    These features are intentionally conservative. More detailed novelty/crowding
    assessment, intent-aware ranking, hypothesis cards, and benchmarking will be
    implemented in separate modules.

    Important:
    - role_classification and therapeutic_direction come from role_classifier.py
    - modality-fit columns come from modality.py
    - evidence-for / evidence-against columns come from evidence_auditor.py
    - confidence and uncertainty columns come from confidence.py
    - this function must not overwrite those outputs
    """
    df = df.copy()

    df["has_resistance_axis_match"] = df["resistance_axis"].ne("unmapped")

    df["initial_priority_note"] = df.apply(
        _make_initial_priority_note,
        axis=1,
    )

    df = reorder_feature_table_columns(df)

    return df


def _make_initial_priority_note(row: pd.Series) -> str:
    """
    Create a short transparent note for the first feature table.
    """
    symbol = row.get("target_symbol", "unknown")
    axis = row.get("matched_resistance_programs", "")
    score = row.get("opentargets_score", None)
    role = row.get("role_classification", "unclear / low-confidence candidate")
    best_modality = row.get("best_modality", "unclear")
    main_limitation = row.get("main_limitation", "not assessed")
    confidence_level = row.get("confidence_level", "not assessed")

    if row.get("resistance_axis") == "unmapped":
        return (
            f"{symbol} is associated with melanoma in Open Targets but is not "
            "currently mapped to a curated anti-PD-1 resistance axis. "
            f"Stable TargetIntel-IO role: {role}. "
            f"Best current modality interpretation: {best_modality}. "
            f"Main limitation: {main_limitation}. "
            f"Confidence: {confidence_level}."
        )

    if pd.notna(score):
        return (
            f"{symbol} is associated with melanoma in Open Targets "
            f"(score={score:.3f}), maps to the curated resistance program "
            f"'{axis}', is classified as '{role}', and has best current "
            f"modality interpretation: {best_modality}. "
            f"Main limitation: {main_limitation}. "
            f"Confidence: {confidence_level}."
        )

    return (
        f"{symbol} maps to the curated resistance program '{axis}', "
        f"is classified as '{role}', and has best current modality "
        f"interpretation: {best_modality}. "
        f"Main limitation: {main_limitation}. "
        f"Confidence: {confidence_level}."
    )


def reorder_feature_table_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reorder columns so the most interpretable TargetIntel-IO fields appear first.
    """
    preferred_columns = [
        # Core target identity
        "target_symbol",
        "target_name",
        "target_id",
        "biotype",
        "disease_id",
        "disease_name",
        "opentargets_score",

        # Resistance-axis ontology
        "resistance_axis",
        "matched_resistance_programs",
        "matched_signature_genes",
        "resistance_axis_score",
        "resistance_axis_confidence",
        "expected_role_from_axis",
        "therapeutic_direction_from_axis",
        "preferred_modalities_from_axis",

        # Stable translational role classifier
        "role_classification",
        "role_confidence",
        "role_rationale",
        "therapeutic_direction",
        "directionality_confidence",
        "directionality_rationale",

        # Modality-aware reasoning
        "antibody_fit",
        "small_molecule_fit",
        "biomarker_fit",
        "io_combination_fit",
        "poor_direct_target_flag",
        "best_modality",
        "modality_rationale",

        # Evidence-for / evidence-against auditor
        "evidence_for",
        "evidence_against",
        "contradiction_score",
        "main_limitation",
        "deprioritization_reason",

        # Confidence and uncertainty
        "data_completeness_score",
        "missing_evidence_fields",
        "confidence_level",
        "uncertainty_reason",

        # First-pass utility fields
        "has_resistance_axis_match",
        "axis_evidence_for",
        "axis_evidence_against",
        "initial_priority_note",

        # Raw Open Targets evidence summaries
        "datatype_scores",
        "datasource_scores",
    ]

    existing_preferred_columns = [
        column for column in preferred_columns if column in df.columns
    ]

    remaining_columns = [
        column for column in df.columns if column not in existing_preferred_columns
    ]

    return df[existing_preferred_columns + remaining_columns]


def save_feature_table(
    df: pd.DataFrame,
    output_path: str | Path = DEFAULT_FEATURE_TABLE_PATH,
) -> Path:
    """
    Save the TargetIntel-IO feature table to CSV.

    Parameters
    ----------
    df:
        Feature table to save.
    output_path:
        Output CSV path.

    Returns
    -------
    pathlib.Path
        Path where the table was saved.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(output_path, index=False)

    return output_path
