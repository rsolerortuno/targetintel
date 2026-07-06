"""
Stable translational role classifier for TargetIntel-IO.

This module assigns each candidate gene a stable biological/translational role.
The role does not change depending on therapeutic-intent ranking mode.

Examples:
- LAG3 -> anti-PD-1 combination target
- B2M -> antigen-presentation resistance biomarker / mechanism
- JAK1 -> IFN-gamma resistance biomarker / mechanism
- BRAF -> tumor-intrinsic driver / small-molecule target
- CDKN2A -> tumor-intrinsic driver / poor direct therapeutic target

The classifier is intentionally rule-based, transparent, and auditable.
It is not a machine-learning model and does not claim de novo target discovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class RoleCall:
    """Container for a translational role classification."""

    role_classification: str
    role_confidence: str
    role_rationale: str
    therapeutic_direction: str
    directionality_confidence: str
    directionality_rationale: str


CHECKPOINT_COMBINATION_TARGETS = {
    "LAG3",
    "TIGIT",
    "HAVCR2",
    "CTLA4",
    "PDCD1",
    "CD274",
}

ANTIGEN_PRESENTATION_BIOMARKERS = {
    "B2M",
    "HLA-A",
    "HLA-B",
    "HLA-C",
    "TAP1",
    "TAP2",
}

IFNG_RESISTANCE_MARKERS = {
    "JAK1",
    "JAK2",
    "IFNGR1",
    "IFNGR2",
    "STAT1",
    "IRF1",
}

MYELOID_TME_TARGETS = {
    "CSF1R",
    "TREM2",
    "MARCO",
    "LILRB1",
    "LILRB2",
    "LILRB3",
    "MERTK",
    "CD163",
}

METABOLIC_IMMUNE_SUPPRESSION_TARGETS = {
    "NT5E",
    "ENTPD1",
    "IDO1",
    "ARG1",
}

TGFB_CAF_EXCLUSION_TARGETS = {
    "TGFB1",
    "TGFBR1",
    "TGFBR2",
    "CXCL12",
    "CXCR4",
    "FAP",
}

MELANOMA_PLASTICITY_MARKERS = {
    "AXL",
    "WNT5A",
    "TWIST2",
    "NGFR",
}

ACTIONABLE_TUMOR_INTRINSIC_DRIVERS = {
    "BRAF",
    "MAP2K1",
    "MAP2K2",
    "KIT",
    "CDK4",
}

TUMOR_INTRINSIC_DRIVERS_POOR_DIRECT_TARGETS = {
    "CDKN2A",
    "PTEN",
    "NF1",
    "BAP1",
    "TP53",
    "RB1",
}

TUMOR_INTRINSIC_DRIVER_BIOMARKERS = {
    "NRAS",
    "MITF",
    "TERT",
}

IMMUNE_CONTEXT_MARKERS = {
    "CD8A",
    "CD8B",
    "GZMB",
    "PRF1",
    "CXCL9",
    "CXCL10",
}

TREG_SUPPRESSION_MARKERS = {
    "FOXP3",
    "IL2RA",
    "IKZF2",
    "TNFRSF18",
}


def normalize_symbol(gene_symbol: Any) -> str:
    """Normalize a gene symbol for rule matching."""
    if pd.isna(gene_symbol):
        return ""

    return str(gene_symbol).strip().upper()


def classify_gene(
    gene_symbol: str,
    resistance_axis: str | None = None,
    expected_role_from_axis: str | None = None,
) -> RoleCall:
    """
    Assign a stable translational role to a candidate gene.

    Parameters
    ----------
    gene_symbol:
        HGNC-style gene symbol.
    resistance_axis:
        Optional resistance-axis annotation from resistance_ontology.py.
    expected_role_from_axis:
        Optional expected role inferred from the ontology.

    Returns
    -------
    RoleCall
        Stable role classification, confidence, rationale, therapeutic
        direction, and directionality rationale.
    """
    symbol = normalize_symbol(gene_symbol)
    resistance_axis = resistance_axis or ""
    expected_role_from_axis = expected_role_from_axis or ""

    if symbol in CHECKPOINT_COMBINATION_TARGETS:
        return RoleCall(
            role_classification="anti-PD-1 combination target",
            role_confidence="high",
            role_rationale=(
                f"{symbol} is part of a curated checkpoint-redundancy axis. "
                "It is best interpreted as an immune-checkpoint or checkpoint-axis "
                "candidate for IO-combination strategies rather than as a generic "
                "melanoma driver."
            ),
            therapeutic_direction="block / inhibit",
            directionality_confidence="high",
            directionality_rationale=(
                "Checkpoint-axis candidates are typically evaluated through blockade "
                "or inhibitory antibody-based strategies."
            ),
        )

    if symbol in ANTIGEN_PRESENTATION_BIOMARKERS:
        return RoleCall(
            role_classification="antigen-presentation resistance biomarker",
            role_confidence="high",
            role_rationale=(
                f"{symbol} maps to antigen-presentation loss biology. This supports "
                "interpretation as a resistance mechanism or patient-stratification "
                "biomarker rather than a direct antibody target."
            ),
            therapeutic_direction="use as biomarker / patient stratification",
            directionality_confidence="high",
            directionality_rationale=(
                "Loss or impairment of antigen presentation is usually more useful "
                "for resistance stratification than direct target blockade."
            ),
        )

    if symbol in IFNG_RESISTANCE_MARKERS:
        return RoleCall(
            role_classification="IFN-gamma resistance mechanism / biomarker",
            role_confidence="high",
            role_rationale=(
                f"{symbol} maps to IFN-gamma signaling resistance biology. This "
                "supports interpretation as a mechanistic resistance marker or "
                "patient-stratification biomarker."
            ),
            therapeutic_direction="use as biomarker / patient stratification",
            directionality_confidence="high",
            directionality_rationale=(
                "IFN-gamma pathway defects often indicate impaired immune-response "
                "competence rather than a straightforward direct therapeutic target."
            ),
        )

    if symbol in MYELOID_TME_TARGETS:
        return RoleCall(
            role_classification="myeloid/TME anti-PD-1 combination target",
            role_confidence="medium-high",
            role_rationale=(
                f"{symbol} maps to suppressive myeloid or tumor-microenvironment "
                "biology. This supports an IO-combination hypothesis, especially "
                "when the target is surface-accessible or myeloid-lineage enriched."
            ),
            therapeutic_direction=(
                "block / deplete / reprogram suppressive myeloid cells"
            ),
            directionality_confidence="medium",
            directionality_rationale=(
                "Myeloid targets may be approached through blockade, depletion, or "
                "reprogramming, but the optimal direction is context-dependent."
            ),
        )

    if symbol in METABOLIC_IMMUNE_SUPPRESSION_TARGETS:
        return RoleCall(
            role_classification="metabolic immune-suppression target",
            role_confidence="medium-high",
            role_rationale=(
                f"{symbol} maps to metabolic immune-suppression biology. This "
                "supports a possible IO-combination rationale, but clinical "
                "translation may depend strongly on pathway context and patient "
                "selection."
            ),
            therapeutic_direction="block / inhibit",
            directionality_confidence="medium-high",
            directionality_rationale=(
                "Metabolic immune-suppression candidates are generally evaluated "
                "through pathway blockade or enzymatic inhibition."
            ),
        )

    if symbol in TGFB_CAF_EXCLUSION_TARGETS:
        return RoleCall(
            role_classification="immune-exclusion / stromal-resistance candidate",
            role_confidence="medium",
            role_rationale=(
                f"{symbol} maps to TGF-beta, CAF, stromal, or immune-exclusion "
                "biology. This supports a tumor-microenvironment resistance "
                "hypothesis rather than a generic tumor-driver interpretation."
            ),
            therapeutic_direction="block / reprogram tumor microenvironment",
            directionality_confidence="medium",
            directionality_rationale=(
                "Stromal and TGF-beta-associated resistance may require blockade "
                "or microenvironment reprogramming, but safety and context are major "
                "considerations."
            ),
        )

    if symbol in MELANOMA_PLASTICITY_MARKERS:
        return RoleCall(
            role_classification="melanoma plasticity / resistance-associated marker",
            role_confidence="medium",
            role_rationale=(
                f"{symbol} maps to melanoma plasticity, dedifferentiation, or "
                "resistant cell-state biology. This may support biomarker or "
                "tumor-intrinsic intervention hypotheses."
            ),
            therapeutic_direction="use as biomarker / inhibit if tractable",
            directionality_confidence="medium",
            directionality_rationale=(
                "Plasticity markers can indicate resistant tumor states, but not all "
                "are direct pharmacological dependencies."
            ),
        )

    if symbol in ACTIONABLE_TUMOR_INTRINSIC_DRIVERS:
        return RoleCall(
            role_classification="tumor-intrinsic driver / small-molecule target",
            role_confidence="high",
            role_rationale=(
                f"{symbol} is best interpreted as a tumor-cell intrinsic melanoma "
                "driver or pathway target. It may be important for melanoma biology "
                "but should not automatically be prioritized as an antibody "
                "IO-combination target."
            ),
            therapeutic_direction="small-molecule inhibition / pathway targeting",
            directionality_confidence="high",
            directionality_rationale=(
                "Actionable tumor-intrinsic drivers are typically more compatible "
                "with small-molecule or pathway-targeting strategies than antibody "
                "checkpoint-combination logic."
            ),
        )

    if symbol in TUMOR_INTRINSIC_DRIVERS_POOR_DIRECT_TARGETS:
        return RoleCall(
            role_classification="tumor-intrinsic driver / poor direct therapeutic target",
            role_confidence="high",
            role_rationale=(
                f"{symbol} is relevant to melanoma biology but is likely a poor "
                "direct therapeutic target, especially for antibody or IO-combination "
                "modalities. It may be more useful for biological interpretation, "
                "risk, pathway context, or patient stratification."
            ),
            therapeutic_direction="avoid as direct target / use as biomarker or pathway context",
            directionality_confidence="high",
            directionality_rationale=(
                "Tumor suppressors and intracellular loss-of-function drivers are "
                "often difficult to target directly and should not be treated as "
                "straightforward antibody targets."
            ),
        )

    if symbol in TUMOR_INTRINSIC_DRIVER_BIOMARKERS:
        return RoleCall(
            role_classification="tumor-intrinsic driver / biomarker",
            role_confidence="medium-high",
            role_rationale=(
                f"{symbol} is relevant to melanoma tumor-intrinsic biology. It may "
                "support tumor stratification or pathway-context interpretation, but "
                "direct therapeutic actionability depends on modality and downstream "
                "pathway tractability."
            ),
            therapeutic_direction="use as biomarker / pathway targeting if appropriate",
            directionality_confidence="medium",
            directionality_rationale=(
                "Some tumor-intrinsic drivers are more useful as biomarkers or pathway "
                "context than as directly druggable targets."
            ),
        )

    if symbol in IMMUNE_CONTEXT_MARKERS:
        return RoleCall(
            role_classification="immune-context marker",
            role_confidence="medium",
            role_rationale=(
                f"{symbol} is best interpreted as an immune-context or immune-infiltration "
                "marker. It may help describe an inflamed versus immune-cold tumor "
                "state, but is not necessarily a causal therapeutic target."
            ),
            therapeutic_direction="use as biomarker / patient stratification",
            directionality_confidence="medium",
            directionality_rationale=(
                "Immune-context markers usually describe tumor immune state rather "
                "than a direct target to inhibit or activate."
            ),
        )

    if symbol in TREG_SUPPRESSION_MARKERS:
        return RoleCall(
            role_classification="Treg-suppression marker / possible IO-combination target",
            role_confidence="medium",
            role_rationale=(
                f"{symbol} maps to regulatory T-cell-associated immune suppression. "
                "It may support patient stratification or IO-combination hypotheses, "
                "but requires careful distinction between lineage marker and safe "
                "therapeutic target."
            ),
            therapeutic_direction="deplete / block / use as biomarker",
            directionality_confidence="medium",
            directionality_rationale=(
                "Treg-associated targets may require depletion, blockade, or biomarker "
                "use, but immune tolerance and safety must be considered."
            ),
        )

    if resistance_axis and resistance_axis != "unmapped":
        return RoleCall(
            role_classification=expected_role_from_axis
            or "resistance-axis-associated candidate",
            role_confidence="medium",
            role_rationale=(
                f"{symbol} maps to curated resistance axis '{resistance_axis}', "
                "but does not yet have a more specific symbol-level rule. The role "
                "is therefore inherited from the resistance ontology."
            ),
            therapeutic_direction="see resistance-axis directionality",
            directionality_confidence="low-medium",
            directionality_rationale=(
                "Directionality is inherited from the ontology because no more "
                "specific symbol-level rule is available yet."
            ),
        )

    return RoleCall(
        role_classification="unclear / low-confidence candidate",
        role_confidence="low",
        role_rationale=(
            f"{symbol} is not currently mapped to a curated anti-PD-1 resistance "
            "axis or symbol-level translational role rule. It may still be associated "
            "with melanoma, but its TargetIntel-IO role is unclear."
        ),
        therapeutic_direction="unclear",
        directionality_confidence="low",
        directionality_rationale=(
            "No curated role, resistance-axis mapping, or directionality rule is "
            "currently available for this candidate."
        ),
    )


def classify_dataframe(
    df: pd.DataFrame,
    gene_column: str = "target_symbol",
    resistance_axis_column: str = "resistance_axis",
    expected_role_column: str = "expected_role_from_axis",
) -> pd.DataFrame:
    """
    Classify all genes in a dataframe.

    Parameters
    ----------
    df:
        Input dataframe containing candidate targets.
    gene_column:
        Column containing gene symbols.
    resistance_axis_column:
        Column containing resistance-axis annotation.
    expected_role_column:
        Column containing ontology-derived expected role.

    Returns
    -------
    pandas.DataFrame
        Input dataframe with stable role-classifier columns appended.
    """
    if gene_column not in df.columns:
        raise KeyError(f"Column not found in dataframe: {gene_column}")

    df = df.copy()

    calls = []

    for _, row in df.iterrows():
        call = classify_gene(
            gene_symbol=row.get(gene_column),
            resistance_axis=row.get(resistance_axis_column, ""),
            expected_role_from_axis=row.get(expected_role_column, ""),
        )
        calls.append(call.__dict__)

    calls_df = pd.DataFrame(calls)

    for column in calls_df.columns:
        df[column] = calls_df[column]

    return df
