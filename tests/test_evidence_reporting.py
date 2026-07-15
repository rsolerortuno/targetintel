"""Issue 208 read-only evidence-card reporting tests."""

from __future__ import annotations

from dataclasses import replace

from targetintel.evidence.reporting import EvidenceReportDecorator, UNVERIFIED_EVIDENCE_LABEL
from targetintel.hypothesis_cards import make_evidence_card_section
from tests.test_evidence_models import evidence_item


def item(**changes: object):
    values = {
        "validation_status": "citation_verified",
        "evidence_family": "efam-v1:root-a",
        "evidence_family_basis": "patient_cohort_id",
        "independence_eligible": True,
        "independence_ineligibility_reason": None,
        "publication_id": "PMID:1",
        "experiment_id": "experiment-1",
        "patient_cohort_id": "cohort-1",
    }
    values.update(changes)
    return evidence_item(**values)


def test_normal_cards_filter_statuses_keep_distinct_members_and_count_roots_only() -> None:
    root_a = item(evidence_id="root-a")
    root_b = item(
        evidence_id="root-b", evidence_family="efam-v1:root-b", publication_id="PMID:2",
        experiment_id="experiment-2", patient_cohort_id="cohort-2",
    )
    composite = item(
        evidence_id="composite", evidence_family="efam-v1:composite",
        evidence_family_basis="composite", derived_from=("root-a", "root-b"),
    )
    ineligible = item(
        evidence_id="ineligible", evidence_family=None, evidence_family_basis="ineligible",
        independence_eligible=False, independence_ineligibility_reason="stable provenance unavailable",
    )
    unverified = item(evidence_id="unverified", validation_status="citation_unverified")
    rejected = item(evidence_id="rejected", validation_status="rejected")
    staging = item(evidence_id="staging", validation_status="semantic_verified")
    records = [root_a, root_b, composite, ineligible, unverified, rejected, staging]

    decorator = EvidenceReportDecorator()
    card = decorator.make_card("MOCK1", records)

    assert card is not None
    assert [record.evidence_id for record in card.items] == ["root-a", "root-b", "composite", "ineligible"]
    assert card.metrics.record_count == 4
    assert card.metrics.publication_count == 2
    assert card.metrics.experiment_count == 2
    assert card.metrics.patient_cohort_count == 2
    assert card.metrics.independent_family_count == 2
    assert card.metrics.ineligible_record_count == 1
    assert [(record.item.evidence_id, record.label) for record in decorator.audit_card_items(records)] == [
        ("unverified", UNVERIFIED_EVIDENCE_LABEL),
        ("rejected", UNVERIFIED_EVIDENCE_LABEL),
    ]


def test_card_rendering_labels_support_and_extraction_confidence_without_aggregation() -> None:
    first = item(evidence_id="first", quoted_span="Exact source sentence.", computed_support=None, extraction_confidence=0.25)
    second = item(evidence_id="second", extraction_confidence=None)
    decorator = EvidenceReportDecorator()
    card = decorator.make_card("MOCK1", [first, second])
    changed_confidence = decorator.make_card("MOCK1", [replace(first, extraction_confidence=0.99), second])

    assert card is not None and changed_confidence is not None
    assert card.metrics == changed_confidence.metrics
    rendered = make_evidence_card_section(card)
    assert "Quoted source text" in rendered
    assert "0.250 (extraction-system confidence, not scientific confidence)" in rendered
    assert "not reported (extraction-system confidence, not scientific confidence)" in rendered
    assert "Evidence record: first" in rendered
    assert "Evidence record: second" in rendered


def test_no_normal_card_is_created_without_verified_records() -> None:
    decorator = EvidenceReportDecorator()
    assert decorator.make_card("MOCK1", [item(validation_status="citation_unverified")]) is None
