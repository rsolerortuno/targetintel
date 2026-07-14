"""Issue 204 immutable DuckDB/Parquet evidence-store tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from targetintel.evidence.models import ProvenanceStep, RetrievalAttempt
from targetintel.evidence.store import EvidenceStore, ImmutableEvidenceError, StorageIntegrityError
from targetintel.evidence.validation import SemanticValidationContext, ValidationError
from tests.test_evidence_models import UTC, evidence_item


def finalized(**changes: object):
    return evidence_item(**changes).with_calculated_record_hash()


def test_finalized_item_round_trips_losslessly_and_duplicate_is_audited(tmp_path: Path) -> None:
    item = finalized()
    with EvidenceStore(tmp_path / "evidence.duckdb", clock=lambda: UTC) as store:
        assert store.insert_finalized_item(item).inserted
        assert store.get_item(item.evidence_id) == item
        result = store.insert_finalized_item(replace(item, evidence_id="new-id"))
        assert (result.evidence_id, result.duplicate) == (item.evidence_id, True)
        assert [event["event_type"] for event in store.audit_events()] == ["insertion", "exact_duplicate"]


def test_store_rejects_unfinalized_or_semantically_invalid_candidates(tmp_path: Path) -> None:
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        with pytest.raises(ValidationError):
            store.insert_finalized_item(evidence_item(validation_status="extracted"))
        invalid = replace(evidence_item(extraction_method="computed", computed_support=None), record_hash="0" * 64)
        with pytest.raises(ValidationError):
            store.insert_finalized_item(invalid)


def test_revisions_are_explicit_and_preserve_immutable_rows(tmp_path: Path) -> None:
    first = finalized(evidence_id="first")
    content_change = finalized(evidence_id="content-change", observation="Changed mock observation.")
    provenance_change = finalized(
        evidence_id="provenance-change",
        provenance_history=[ProvenanceStep("curation", UTC, {"fixture": "revised"})],
    )
    status_change = finalized(evidence_id="status-change", validation_status="rejected")
    family_change = finalized(
        evidence_id="family-change",
        evidence_family="efam-v1:mock-family",
        evidence_family_basis="stable_source_record",
        independence_eligible=True,
        independence_ineligibility_reason=None,
    )
    with EvidenceStore(tmp_path / "evidence.duckdb", clock=lambda: UTC) as store:
        store.insert_finalized_item(first)
        for changed in (content_change, provenance_change, status_change, family_change):
            store.insert_finalized_item(changed)

        assert store.revisions_for("first") == []
        store.link_revision("content-change", "first", "content corrected")
        store.link_revision("provenance-change", "first", "provenance corrected")
        store.link_revision("status-change", "first", "final status corrected")
        store.link_revision("family-change", "first", "family assignment corrected")

        assert store.get_item("first") == first
        assert store.revisions_for("first") == [
            ("content-change", "first", "content corrected"),
            ("family-change", "first", "family assignment corrected"),
            ("provenance-change", "first", "provenance corrected"),
            ("status-change", "first", "final status corrected"),
        ]
        changed_same_id = finalized(evidence_id="first", observation="Mutated in place")
        with pytest.raises(ImmutableEvidenceError):
            store.insert_finalized_item(changed_same_id)


def test_same_source_items_are_not_automatically_revision_linked(tmp_path: Path) -> None:
    first = finalized(evidence_id="first")
    distinct_observation = finalized(
        evidence_id="distinct-observation", observation="A distinct mock observation."
    )

    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        store.insert_finalized_item(first)
        store.insert_finalized_item(distinct_observation)

        assert store.get_item("first") == first
        assert store.get_item("distinct-observation") == distinct_observation
        assert store.revisions_for("first") == []
        assert store.revisions_for("distinct-observation") == []


def test_ineligible_evidence_is_stored_without_an_evidence_family(tmp_path: Path) -> None:
    item = finalized()

    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        store.insert_finalized_item(item)

        stored_family, eligible = store._connection.execute(
            "SELECT evidence_family, independence_eligible FROM evidence_items WHERE evidence_id = ?",
            [item.evidence_id],
        ).fetchone()
        assert stored_family is None
        assert eligible is False
        assert store.get_item(item.evidence_id) == item


def test_derived_links_must_resolve_and_are_preserved(tmp_path: Path) -> None:
    parent = finalized(evidence_id="parent")
    child = replace(evidence_item(evidence_id="child", derived_from=["parent"]), record_hash=None)
    child = child.with_calculated_record_hash(SemanticValidationContext({"parent": parent}))
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        store.insert_finalized_item(parent)
        store.insert_finalized_item(child)
        assert store.get_item("child") == child
        with pytest.raises(ValidationError):
            store.insert_finalized_item(finalized(evidence_id="dangling", derived_from=["missing"]))


@pytest.mark.parametrize(
    ("status", "result_count", "error_category"),
    [("success", 1, None), ("success_zero_results", 0, None), ("failed", None, "network"), ("not_executed", None, None)],
)
def test_retrieval_attempts_are_independent_and_distinct(tmp_path: Path, status: str, result_count: int | None, error_category: str | None) -> None:
    attempt = RetrievalAttempt(status, "MOCK1", "melanoma", None, "mock", "query", UTC, status, result_count, error_category, None)
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        store.record_retrieval_attempt(attempt)
        assert store.get_retrieval_attempt(status) == attempt
        assert store.list_items() == []
        assert store.list_retrieval_attempts(status=status) == [attempt]


def test_invalid_failure_and_snapshot_immutability(tmp_path: Path) -> None:
    item = finalized()
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        failed = RetrievalAttempt("bad", "MOCK1", "melanoma", None, "mock", "query", UTC, "failed", None, None, None)
        with pytest.raises(ValidationError):
            store.record_retrieval_attempt(failed)
        store.insert_finalized_item(item)
        before = store.audit_events()
        snapshot = store.export_snapshot(tmp_path / "snapshot")
        assert EvidenceStore.verify_snapshot(snapshot).table_rows["evidence_items"] == 1
        assert store.audit_events()[:-1] == before
        assert store.audit_events()[-1]["event_type"] == "export"
        assert store.audit_events()[-1]["details"] == {"snapshot_path": str(snapshot)}
        with pytest.raises(FileExistsError):
            store.export_snapshot(snapshot)


def test_corrupt_hash_collision_is_audited_without_partial_insert(tmp_path: Path) -> None:
    first = finalized()
    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        store.insert_finalized_item(first)
        # This simulates an externally corrupted legacy store: normal callers
        # cannot construct a mismatched SHA-256 payload through the public API.
        store._connection.execute("UPDATE evidence_items SET canonical_json = ? WHERE evidence_id = ?", ["{}", first.evidence_id])
        candidate = replace(first, evidence_id="collision")
        with pytest.raises(StorageIntegrityError):
            store.insert_finalized_item(candidate)
        assert store.get_item("collision") is None
        assert store.audit_events()[-1]["event_type"] == "collision"


def test_absent_retrieval_attempt_is_distinct_from_explicit_not_executed(
    tmp_path: Path,
) -> None:
    attempt = RetrievalAttempt(
        "explicit-not-executed",
        "MOCK1",
        "melanoma",
        None,
        "mock",
        "query",
        UTC,
        "not_executed",
        None,
        None,
        None,
    )

    with EvidenceStore(tmp_path / "evidence.duckdb") as store:
        # No row means that no retrieval state was recorded.
        assert store.get_retrieval_attempt("missing-attempt") is None
        assert store.list_retrieval_attempts() == []
        assert store.list_items() == []

        # An explicit not_executed row is a different recorded state.
        store.record_retrieval_attempt(attempt)

        assert store.get_retrieval_attempt("missing-attempt") is None
        assert store.get_retrieval_attempt("explicit-not-executed") == attempt
        assert store.list_retrieval_attempts(status="not_executed") == [attempt]
        assert store.list_items() == []
