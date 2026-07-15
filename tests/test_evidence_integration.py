"""Issue 208 optional post-ranking evidence-store integration tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from pandas.testing import assert_frame_equal

import targetintel.pipeline as pipeline
from targetintel.evidence.models import ProvenanceStep, RetrievalAttempt
from targetintel.evidence.pipeline_integration import load_evidence_cards
from targetintel.evidence.store import EvidenceStore
from tests.test_evidence_models import UTC, evidence_item


def finalized_verified(**changes: object):
    values = {
        "validation_status": "citation_verified",
        "provenance_history": [
            ProvenanceStep("citation_verification", UTC, {"success": True}),
        ],
    }
    values.update(changes)
    return evidence_item(**values).with_calculated_record_hash()


def test_load_evidence_cards_reads_finalized_records_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "evidence.duckdb"
    verified = finalized_verified(evidence_id="verified")
    audit_only = evidence_item(evidence_id="audit-only").with_calculated_record_hash()
    with EvidenceStore(path) as store:
        store.insert_finalized_item(verified)
        store.insert_finalized_item(audit_only)
        before_verified = store.get_item("verified")
        before_audit = store.get_item("audit-only")

    cards = load_evidence_cards(path, ["MOCK1"])

    assert list(cards) == ["MOCK1"]
    assert [item.evidence_id for item in cards["MOCK1"].items] == ["verified"]
    with EvidenceStore(path) as store:
        assert store.get_item("verified") == before_verified
        assert store.get_item("audit-only") == before_audit


def test_missing_store_and_zero_or_failed_retrievals_create_no_evidence_cards(tmp_path: Path) -> None:
    assert load_evidence_cards(tmp_path / "absent.duckdb", ["MOCK1"]) == {}

    path = tmp_path / "evidence.duckdb"
    with EvidenceStore(path) as store:
        store.record_retrieval_attempt(RetrievalAttempt(
            "zero", "MOCK1", "melanoma", None, "mock", "query", UTC,
            "success_zero_results", 0, None, None,
        ))
        store.record_retrieval_attempt(RetrievalAttempt(
            "failed", "MOCK2", "melanoma", None, "mock", "query", UTC,
            "failed", None, "network", None,
        ))

    assert load_evidence_cards(path, ["MOCK1", "MOCK2"]) == {}


def _store_verified_item(path: Path, *, extraction_confidence: float) -> None:
    with EvidenceStore(path) as store:
        store.insert_finalized_item(finalized_verified(
            evidence_id=f"verified-{extraction_confidence}",
            extraction_confidence=extraction_confidence,
        ))


def test_evidence_integration_preserves_baseline_feature_scores_classifications_and_rankings(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Evidence decoration is strictly post-ranking and cannot mutate baseline data."""
    feature_df = pd.DataFrame({
        "target_symbol": ["MOCK1", "MOCK2"],
        "stable_role": ["therapeutic_target", "resistance_biomarker"],
        "antibody_io_score": [8.0, 2.0],
    })
    ranked_df = feature_df.assign(
        antibody_io_rank=[1, 2],
        biomarker_rank=[2, 1],
        small_molecule_rank=[2, 1],
    )
    rendered_frames: list[pd.DataFrame] = []
    rendered_evidence_cards: list[object | None] = []

    monkeypatch.setattr(pipeline, "build_feature_table", lambda **_: feature_df.copy())
    monkeypatch.setattr(pipeline, "build_intent_rankings", lambda dataframe: ranked_df.copy())

    def save_dataframe(dataframe: pd.DataFrame, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_csv(output_path, index=False)
        return output_path

    monkeypatch.setattr(pipeline, "save_feature_table", save_dataframe)
    monkeypatch.setattr(pipeline, "save_ranked_targets", save_dataframe)

    def write_cards(dataframe: pd.DataFrame, **kwargs: object) -> list[Path]:
        rendered_frames.append(dataframe.copy())
        rendered_evidence_cards.append(kwargs.get("evidence_cards"))
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "MOCK1.md"
        path.write_text("# MOCK1\n", encoding="utf-8")
        return [path]

    def write_html(dataframe: pd.DataFrame, **kwargs: object) -> list[Path]:
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "index.html"
        path.write_text("<html></html>\n", encoding="utf-8")
        return [path]

    monkeypatch.setattr(pipeline, "write_top_target_cards", write_cards)
    monkeypatch.setattr(pipeline, "write_top_html_reports", write_html)
    monkeypatch.setattr(pipeline, "generate_summary_figures", lambda *_args, **_kwargs: [])

    store_path = tmp_path / "evidence.duckdb"
    _store_verified_item(store_path, extraction_confidence=0.25)
    without_evidence = pipeline.run_core_pipeline(project_root=tmp_path / "without")
    with_evidence = pipeline.run_core_pipeline(
        project_root=tmp_path / "with",
        evidence_store_path=store_path,
    )

    assert_frame_equal(
        pd.read_csv(without_evidence.feature_table),
        pd.read_csv(with_evidence.feature_table),
        check_exact=True,
    )
    assert without_evidence.feature_table.read_bytes() == with_evidence.feature_table.read_bytes()
    assert_frame_equal(
        pd.read_csv(without_evidence.ranked_targets),
        pd.read_csv(with_evidence.ranked_targets),
        check_exact=True,
    )
    assert without_evidence.ranked_targets.read_bytes() == with_evidence.ranked_targets.read_bytes()
    assert len(rendered_frames) == 2
    assert_frame_equal(rendered_frames[0], rendered_frames[1], check_exact=True)
    assert rendered_evidence_cards == [None, rendered_evidence_cards[1]]
    assert list(rendered_evidence_cards[1]) == ["MOCK1"]


def test_extraction_confidence_cannot_change_deterministic_pipeline_outputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Extraction-system confidence is presentation metadata, never a ranking input."""
    feature_df = pd.DataFrame({"target_symbol": ["MOCK1"], "stable_role": ["therapeutic_target"]})
    ranked_df = feature_df.assign(antibody_io_score=[7.0], antibody_io_rank=[1])
    monkeypatch.setattr(pipeline, "build_feature_table", lambda **_: feature_df.copy())
    monkeypatch.setattr(pipeline, "build_intent_rankings", lambda dataframe: ranked_df.copy())

    def save_dataframe(dataframe: pd.DataFrame, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        dataframe.to_csv(output_path, index=False)
        return output_path

    monkeypatch.setattr(pipeline, "save_feature_table", save_dataframe)
    monkeypatch.setattr(pipeline, "save_ranked_targets", save_dataframe)
    monkeypatch.setattr(pipeline, "write_top_target_cards", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(pipeline, "write_top_html_reports", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(pipeline, "generate_summary_figures", lambda *_args, **_kwargs: [])

    low_confidence_store = tmp_path / "low.duckdb"
    high_confidence_store = tmp_path / "high.duckdb"
    _store_verified_item(low_confidence_store, extraction_confidence=0.01)
    _store_verified_item(high_confidence_store, extraction_confidence=0.99)

    low_confidence = pipeline.run_core_pipeline(
        project_root=tmp_path / "low-output",
        evidence_store_path=low_confidence_store,
    )
    high_confidence = pipeline.run_core_pipeline(
        project_root=tmp_path / "high-output",
        evidence_store_path=high_confidence_store,
    )

    assert low_confidence.feature_table.read_bytes() == high_confidence.feature_table.read_bytes()
    assert low_confidence.ranked_targets.read_bytes() == high_confidence.ranked_targets.read_bytes()
