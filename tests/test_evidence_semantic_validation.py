"""Issue 203 semantic and cross-field evidence validation tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from targetintel.evidence.models import ProvenanceStep
from targetintel.evidence.validation import (
    SemanticValidationContext,
    ValidationError,
    require_finalizable,
    require_semantically_valid,
    validate_semantic,
)
from tests.test_evidence_models import UTC, evidence_item


def issue_fields(item: object, context: SemanticValidationContext | None = None) -> set[str]:
    return {issue.field for issue in validate_semantic(item, context)}  # type: ignore[arg-type]


def eligible_item(**changes: object):
    return evidence_item(
        evidence_family="efam-v1:mock",
        evidence_family_basis="stable_source_record",
        independence_eligible=True,
        independence_ineligibility_reason=None,
        **changes,
    )


def test_literature_requires_quote_and_computed_database_requires_support() -> None:
    literature = eligible_item(publication_id="PMID:MOCK", quoted_span=None)
    computed = eligible_item(extraction_method="computed", computed_support=None)
    valid_computed = eligible_item(extraction_method="computed", quoted_span=None, computed_support="result row 7")

    assert "quoted_span" in issue_fields(literature)
    assert "computed_support" in issue_fields(computed)
    assert "computed_support" not in issue_fields(valid_computed)


def test_manual_curation_requires_support_and_complete_review_provenance() -> None:
    incomplete = eligible_item(validation_status="manually_curated", computed_support=None)
    complete = eligible_item(
        validation_status="manually_curated",
        provenance_history=[
            ProvenanceStep(
                "manual_review",
                UTC,
                {
                    "curator_id": "curator-1",
                    "review_rationale": "Confirmed fixture extraction.",
                    "reviewed_computed_output": "frozen result row 7",
                },
            )
        ],
    )

    assert {"quoted_span", "provenance_history"} <= issue_fields(incomplete)
    require_semantically_valid(complete)
    assert "source_id" in issue_fields(replace(complete, source_id="unknown"))


def test_parent_links_must_resolve_and_derived_graph_must_be_acyclic() -> None:
    child = eligible_item(evidence_id="child", derived_from=["parent"])
    parent = eligible_item(evidence_id="parent")

    assert "derived_from" in issue_fields(child)
    require_semantically_valid(child, SemanticValidationContext({"parent": parent}))

    cyclic_parent = replace(parent, derived_from=("child",))
    issues = validate_semantic(child, SemanticValidationContext({"parent": cyclic_parent}))

    assert any("cycle" in issue.message for issue in issues)

    finalized = replace(child, validation_status="citation_unverified")
    assert finalized.with_calculated_record_hash(SemanticValidationContext({"parent": parent})).record_hash is not None


def test_derived_exact_content_comparison_accepts_validation_context() -> None:
    parent = eligible_item(evidence_id="parent")
    context = SemanticValidationContext({"parent": parent})
    first = eligible_item(evidence_id="child-1", derived_from=["parent"])
    same_content = replace(first, evidence_id="child-2")

    assert first.has_exact_content(same_content, context)


def test_eligible_and_ineligible_family_fields_are_cross_field_consistent() -> None:
    assert {"evidence_family", "evidence_family_basis", "independence_ineligibility_reason"} <= issue_fields(
        evidence_item(
            evidence_family=None,
            evidence_family_basis="ineligible",
            independence_eligible=True,
            independence_ineligibility_reason="should not be present",
        )
    )
    assert {"evidence_family", "evidence_family_basis", "independence_ineligibility_reason"} <= issue_fields(
        evidence_item(
            evidence_family="efam-v1:bad",
            evidence_family_basis="publication_id",
            independence_eligible=False,
            independence_ineligibility_reason=None,
        )
    )


def test_required_cohort_and_experiment_context_is_enforced_without_vocabularies() -> None:
    clinical = eligible_item(evidence_type="clinical_cohort", patient_cohort_id=None)
    experiment = eligible_item(evidence_type="functional_genomics", experiment_id=None)
    contextual = eligible_item(comparison="A versus B", endpoint="response")

    assert "patient_cohort_id" in issue_fields(clinical)
    assert "experiment_id" in issue_fields(experiment)
    assert "comparison" in issue_fields(contextual)


def test_observation_interpretation_status_and_paired_measurements_are_separate() -> None:
    mocked = eligible_item(interpretation="not permitted for mock extraction")
    unverified_citation = eligible_item(validation_status="citation_verified", quoted_span="Exact source text.")
    paired = eligible_item(effect_size=0.4, effect_size_metric=None, uncertainty_metric="standard_error")
    verified = eligible_item(
        validation_status="citation_verified",
        quoted_span="Exact source text.",
        provenance_history=[ProvenanceStep("citation_verification", UTC, {"success": True})],
    )

    assert "interpretation" in issue_fields(mocked)
    assert "validation_status" in issue_fields(unverified_citation)
    assert {"effect_size_metric", "uncertainty_metric"} <= issue_fields(paired)
    require_semantically_valid(verified)


def test_uncertainty_metrics_and_sample_size_have_no_unspecified_p_value_semantics() -> None:
    """The contract has no p-value field or uncertainty-metric vocabulary."""
    item = eligible_item(uncertainty=0.05, uncertainty_metric="p_value", sample_size=None)

    assert not {"uncertainty_metric", "sample_size"} & issue_fields(item)


def test_semantic_invalidity_prevents_finalization_without_mutating_item() -> None:
    item = eligible_item(extraction_method="computed", computed_support=None)

    with pytest.raises(ValidationError, match="computed_support"):
        require_finalizable(item)
    assert item.computed_support is None
