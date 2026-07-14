"""Issue 202 contract serialization and identity tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from targetintel.evidence.models import EvidenceItem, ProvenanceStep, RetrievalAttempt


UTC = datetime(2026, 7, 12, 10, 11, 12, 345678, tzinfo=timezone.utc)


def evidence_item(**changes: object) -> EvidenceItem:
    values: dict[str, object] = {
        "evidence_id": "ev_mock_1", "target_symbol": "MOCK1", "target_id": None,
        "disease_name": "melanoma", "disease_id": "MONDO:MOCK", "treatment_name": None,
        "treatment_id": None, "evidence_type": "database_assertion", "evidence_direction": "neutral",
        "observation": "A mock observation.", "interpretation": None, "source": "Mock source",
        "source_id": "mock-1", "document_location": None, "quoted_span": None,
        "computed_support": "mock output", "publication_id": None, "source_dataset_id": None,
        "patient_cohort_id": None, "experiment_id": None, "comparison": None, "endpoint": None,
        "data_modality": None, "species": "human", "model_system": "database", "sample_context": None,
        "effect_size": None, "effect_size_metric": None, "uncertainty": None, "uncertainty_metric": None,
        "sample_size": None, "extraction_method": "mock", "extraction_confidence": 1.0,
        "validation_status": "citation_unverified", "retrieved_at": UTC, "data_release": None,
        "derived_from": [], "evidence_family": None, "evidence_family_algorithm_version": "efam-v1",
        "evidence_family_basis": "ineligible", "independence_eligible": False,
        "independence_ineligibility_reason": "stable provenance unavailable", "record_hash": None,
        "provenance_history": [ProvenanceStep("extraction", UTC, {"fixture": "mock"})],
    }
    values.update(changes)
    return EvidenceItem(**values)  # type: ignore[arg-type]


def test_evidence_item_round_trip_preserves_nulls_datetimes_lists_and_provenance() -> None:
    item = evidence_item()
    restored = EvidenceItem.from_dict(item.to_dict())

    assert restored == item
    assert restored.to_dict()["target_id"] is None
    assert restored.to_dict()["retrieved_at"] == "2026-07-12T10:11:12.345678Z"


def test_retrieval_attempt_round_trip_preserves_complete_contract() -> None:
    attempt = RetrievalAttempt("ra_1", "MOCK1", "melanoma", None, "Mock source", "MOCK1 melanoma", UTC, "success_zero_results", 0, None, None)

    assert RetrievalAttempt.from_dict(attempt.to_dict()) == attempt


def test_hash_is_deterministic_and_exact_content_ignores_stable_record_id() -> None:
    first = evidence_item().with_calculated_record_hash()
    same_content_new_id = replace(first, evidence_id="ev_mock_2", record_hash=None).with_calculated_record_hash()

    assert first.record_hash == first.calculate_record_hash()
    assert first.record_hash == same_content_new_id.record_hash
    assert first.has_exact_content(same_content_new_id)


def test_hash_normalizes_non_quote_whitespace_but_preserves_quote_internal_spaces() -> None:
    base = evidence_item(observation="  mock\t observation\r\n", quoted_span="A  quoted\t span\r\n")
    equivalent = evidence_item(observation="mock observation\n", quoted_span="A  quoted\t span\n")
    changed_quote = evidence_item(observation="mock observation", quoted_span="A quoted span\n")

    assert base.calculate_record_hash() == equivalent.calculate_record_hash()
    assert base.calculate_record_hash() != changed_quote.calculate_record_hash()


def test_operational_provenance_timestamp_is_not_hash_covered() -> None:
    first = evidence_item(provenance_history=[ProvenanceStep("audit", UTC, {"event": "read"}, True)])
    second = evidence_item(provenance_history=[ProvenanceStep("audit", UTC.replace(second=13), {"event": "read"}, True)])

    assert first.calculate_record_hash() == second.calculate_record_hash()
