"""Synthetic, isolated checks for the portable DepMap report contract."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import math

import pytest

from targetintel.functional_dependency.report_contract import (
    DependencyReportEvidence, build_dependency_report_evidence,
)


LIMITATIONS = [
    "DepMap cell-line dependency is not clinical anti-PD-1 response evidence.",
    "Absence of tumor-cell dependency does not invalidate an immune target.",
    "Broad dependency may represent general essentiality.",
    "Cell-line models do not reproduce the complete tumor microenvironment.",
    "Candidate activation requires explicit human review.",
]


def available(**changes: object) -> DependencyReportEvidence:
    values: dict[str, object] = {
        "format_version": "v1", "release_identifier": "DepMap_Public_26Q1",
        "release_manifest_id": "manifest", "configuration_id": "configuration",
        "scientific_closure_identity": "closure", "context_identity": "melanoma_anti_pd1:v1",
        "gene_symbol": "BRAF", "canonical_gene_identity": "BRAF:673",
        "profile_available": True, "coverage_status": "sufficient_complete_coverage",
        "model_count": 10, "context_model_count": 4, "reference_model_count": 6,
        "available_context_observations": 4, "available_reference_observations": 6,
        "coverage_fraction": 1.0, "missing_value_state": "target_resolved_both_matrices",
        "unavailable_reason": None, "gene_effect": {"median": 0.0, "measured_model_count": 4},
        "dependency_probability": {"median": None, "measured_model_count": 4},
        "context_reference_comparison": {"gene_effect_context_minus_non_context_median": -0.2},
        "selectivity": {"available": True, "value": 50.0},
        "dependency_interpretation_state": "valid", "baseline_rank": 7,
        "dependency_aware_candidate_rank": 5, "rank_delta": -2,
        "integration_state": "human_review_required", "baseline_preserved": True,
        "production_activation_enabled": False, "approved_authorization_emitted": False,
        "candidate_activation_readiness": "blocked", "human_review_required": True,
        "limitations": LIMITATIONS, "provenance": {"source_artifact_names": ["release_summary.json", "candidate_overlay.tsv"], "snapshot_format": "v1"},
    }
    values.update(changes)
    return DependencyReportEvidence.create(**values)


def unavailable() -> DependencyReportEvidence:
    return available(profile_available=False, coverage_status="not_available", canonical_gene_identity=None,
                     model_count=None, context_model_count=None, reference_model_count=None,
                     available_context_observations=None, available_reference_observations=None,
                     coverage_fraction=None, unavailable_reason="target_unresolved", gene_effect=None,
                     dependency_probability=None, context_reference_comparison=None, selectivity=None)


def test_available_round_trip_identity_json_and_immutability() -> None:
    evidence = available()
    assert evidence.rank_delta == -2
    assert evidence.gene_effect["median"] == 0.0  # zero is not missing
    assert evidence.dependency_probability["median"] is None
    assert evidence.canonical_json() == evidence.canonical_json()
    assert json.loads(evidence.canonical_json()) == evidence.to_dict()
    assert DependencyReportEvidence.from_dict(evidence.to_dict()) == evidence
    with pytest.raises(FrozenInstanceError): evidence.gene_symbol = "NRAS"  # type: ignore[misc]
    with pytest.raises(TypeError): evidence.provenance["x"] = "y"  # type: ignore[index]
    with pytest.raises(TypeError): evidence.gene_effect["median"] = 2  # type: ignore[index]


def test_unavailable_is_distinct_and_source_data_is_defensively_frozen() -> None:
    source = {"source_artifact_names": ["release_summary.json"]}
    evidence = available(provenance=source)
    source["source_artifact_names"].append("changed")
    assert evidence.provenance["source_artifact_names"] == ("release_summary.json",)
    missing = unavailable()
    assert missing.coverage_status == "not_available" and missing.gene_effect is None


def test_identity_is_order_independent_and_excludes_portable_operational_provenance() -> None:
    first = available(provenance={"source_artifact_names": ["a"], "operational_note": "one"})
    second = available(provenance={"operational_note": "two", "source_artifact_names": ["a"]}, gene_effect={"measured_model_count": 4, "median": 0.0})
    assert first.evidence_id == second.evidence_id


@pytest.mark.parametrize("changes", [
    {"coverage_status": "unknown"}, {"context_model_count": -1},
    {"coverage_fraction": 1.1}, {"available_context_observations": 5},
    {"gene_effect": {"median": math.nan}}, {"dependency_probability": {"median": math.inf}},
    {"rank_delta": 2}, {"baseline_preserved": False},
    {"production_activation_enabled": True}, {"approved_authorization_emitted": True},
    {"human_review_required": False}, {"provenance": {"artifact": "/home/user/private"}},
    {"provenance": {"artifact": "C:\\private\\artifact"}},
])
def test_invalid_invariants_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError): available(**changes)


def test_unavailable_metrics_and_available_missing_coverage_are_rejected() -> None:
    with pytest.raises(ValueError): unavailable().to_dict() and available(profile_available=False, coverage_status="not_available", gene_effect={"median": 0.0})
    with pytest.raises(ValueError): available(coverage_fraction=None)


def test_pure_builder_preserves_portable_snapshot_records() -> None:
    summary = {"release_identifier": "DepMap_Public_26Q1", "release_manifest_id": "manifest", "configuration_id": "configuration", "scientific_closure_identity": "closure", "context_identity": "melanoma_anti_pd1:v1", "baseline_preserved": True, "production_activation_enabled": False, "approved_authorization_emitted": False, "human_review_required": True, "integration_state": "human_review_required", "candidate_activation_readiness": "blocked", "limitations": LIMITATIONS}
    profile = {"target_identity": {"normalized_request": "BRAF", "canonical_identity": "BRAF:673"}, "release_manifest_id": "manifest", "context_identity": "melanoma_anti_pd1:v1", "terminal_status": "valid", "payload": {"coverage_status": "sufficient_complete_coverage", "matrix_coverage_status": "target_resolved_both_matrices", "model_coverage": {"context_model_count": 2, "non_context_model_count": 3, "pan_cancer_model_count": 5}, "summaries": {"context": {"gene_effect": {"median": 0.0, "measured_model_count": 2}, "dependency_probability": {"median": 0.5, "measured_model_count": 2}}, "non_context": {"gene_effect": {"median": -0.1, "measured_model_count": 3}}}, "contrasts": {}, "empirical_context_lineage_position": {}, "limitations": []}}
    evidence = build_dependency_report_evidence(release_summary=summary, profile_record=profile, overlay_record={"baseline_rank": 4, "candidate_rank": 3}, provenance={"source_artifact_names": ["selected_target_profiles.tsv"]})
    assert evidence.evidence_id and evidence.rank_delta == -1 and evidence.gene_effect["median"] == 0.0


@pytest.mark.parametrize(("record", "field", "value"), [
    ("profile", "release_manifest_id", "other-manifest"),
    ("profile", "context_identity", "other-context"),
    ("overlay", "canonical_target_identity", "NRAS:4893"),
    ("overlay", "original_target_identifier", "NRAS"),
])
def test_pure_builder_rejects_incompatible_record_identities(
    record: str, field: str, value: str,
) -> None:
    summary = {"release_identifier": "DepMap_Public_26Q1", "release_manifest_id": "manifest", "configuration_id": "configuration", "scientific_closure_identity": "closure", "context_identity": "melanoma_anti_pd1:v1", "baseline_preserved": True, "production_activation_enabled": False, "approved_authorization_emitted": False, "human_review_required": True, "integration_state": "human_review_required", "candidate_activation_readiness": "blocked", "limitations": LIMITATIONS}
    profile = {"target_identity": {"normalized_request": "BRAF", "canonical_identity": "BRAF:673"}, "release_manifest_id": "manifest", "context_identity": "melanoma_anti_pd1:v1", "terminal_status": "valid", "payload": {"coverage_status": "sufficient_complete_coverage", "model_coverage": {"context_model_count": 2, "non_context_model_count": 3, "pan_cancer_model_count": 5}, "summaries": {"context": {"gene_effect": {"median": 0.0, "measured_model_count": 2}}, "non_context": {"gene_effect": {"median": -0.1, "measured_model_count": 3}}}}}
    overlay = {"baseline_rank": 4, "candidate_rank": 3}
    (profile if record == "profile" else overlay)[field] = value
    with pytest.raises(ValueError, match=field):
        build_dependency_report_evidence(release_summary=summary, profile_record=profile, overlay_record=overlay, provenance={"source_artifact_names": ["selected_target_profiles.tsv"]})
