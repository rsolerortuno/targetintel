"""Issue 206 deterministic offline mock-extractor tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pytest

from targetintel.evidence.extractor import Extractor, MockExtractor, SourceDocument
from targetintel.evidence.models import EvidenceItem, canonical_json
from targetintel.evidence.store import EvidenceStore
from targetintel.evidence.validation import require_semantically_valid, require_valid


FIXTURES = Path(__file__).parent / "fixtures" / "evidence"


def document(name: str) -> SourceDocument:
    return SourceDocument.from_dict(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def test_extractor_interface_is_usable_independently() -> None:
    class EmptyExtractor:
        def extract(self, source: SourceDocument) -> Sequence[EvidenceItem]:
            return ()

    extractor: Extractor = EmptyExtractor()
    assert extractor.extract(document("mock_literature_document.json")) == ()


def test_literature_candidates_are_literal_extracted_staging_items() -> None:
    source = document("mock_literature_document.json")
    candidates = MockExtractor().extract(source)

    assert [item.evidence_direction for item in candidates] == [
        "supports_biomarker", "contradicts_target", "limits_target",
    ]
    assert all(item.validation_status == "extracted" for item in candidates)
    assert all(item.extraction_method == "mock" for item in candidates)
    assert all(item.interpretation is None and item.record_hash is None for item in candidates)
    assert all(item.quoted_span in source.source_text for item in candidates)
    assert all(item.document_location == source.document_location for item in candidates)
    assert all(item.publication_id == source.publication_id for item in candidates)
    for item in candidates:
        require_valid(item)
        require_semantically_valid(item)


def test_computed_fixture_preserves_auditable_metadata_without_quote() -> None:
    source = document("mock_computed_document.json")
    item = MockExtractor().extract(source)[0]

    assert item.quoted_span is None
    assert item.computed_support == "fixture=mock_computed_document_v1; structured_content.rows[0]; transformation=none"
    assert (item.source_dataset_id, item.patient_cohort_id, item.experiment_id) == (
        source.source_dataset_id, source.patient_cohort_id, source.experiment_id,
    )
    assert (item.comparison, item.endpoint, item.data_modality) == (
        "fixture group A versus fixture group B", "fixture measurement", "mock_assay",
    )
    assert (item.effect_size, item.uncertainty, item.sample_size) == (-0.25, 0.1, 3)
    require_semantically_valid(item)


def test_extraction_never_persists_items_or_creates_retrieval_attempts(tmp_path: Path) -> None:
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        candidates = MockExtractor().extract(document("mock_literature_document.json"))
        assert candidates
        assert store.list_items() == []
        assert store.list_retrieval_attempts() == []


def test_ids_timestamps_provenance_and_serialization_are_deterministic() -> None:
    source = document("mock_literature_document.json")
    extractor = MockExtractor(evidence_id_factory=lambda _d, candidate, index: f"candidate-{index}-{candidate['fixture_candidate_id']}")
    first = extractor.extract(source)
    second = extractor.extract(source)

    assert first == second
    assert canonical_json([item.to_dict() for item in first]) == canonical_json([item.to_dict() for item in second])
    assert [item.evidence_id for item in first] == [
        "candidate-0-01-supporting", "candidate-1-02-contradictory", "candidate-2-03-limiting",
    ]
    assert all(item.retrieved_at == datetime(2026, 7, 15, 10, tzinfo=timezone.utc) for item in first)
    assert all(item.provenance_history[0].details["method"] == "mock" for item in first)
    assert all(item.provenance_history[0].details["fixture_source"] == source.fixture_id for item in first)
    assert all(item.evidence_family is None and item.evidence_family_basis == "ineligible" for item in first)


def test_malformed_fixture_and_nonliteral_quote_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="candidates"):
        SourceDocument.from_dict({"fixture_id": "x"})
    source = document("mock_literature_document.json")
    altered = SourceDocument(
        **{**source.__dict__, "candidates": ({**source.candidates[0], "quoted_span": "not present"},)}
    )
    with pytest.raises(ValueError, match="occur literally"):
        MockExtractor().extract(altered)


def test_clock_is_injected_when_fixture_has_no_timestamp() -> None:
    source = document("mock_computed_document.json")
    timeless = SourceDocument(**{**source.__dict__, "retrieved_at": None})
    clock_time = datetime(2026, 7, 15, 13, tzinfo=timezone.utc)
    assert MockExtractor(clock=lambda: clock_time).extract(timeless)[0].retrieved_at == clock_time
