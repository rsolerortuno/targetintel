"""End-to-end regression coverage for the fully offline v0.3.0 mock demo."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "examples" / "llm" / "run_v030_mock_demo.py"
spec = importlib.util.spec_from_file_location("v030_mock_demo", SCRIPT)
demo = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(demo)


def _run(path: Path) -> dict:
    return demo.run_demo(path)


def test_v030_demo_composes_public_offline_workflow(tmp_path: Path) -> None:
    summary = _run(tmp_path / "demo")
    artifacts = tmp_path / "demo" / "artifacts"
    extraction = json.loads((artifacts / "extraction.json").read_text())
    audit = json.loads((artifacts / "audit.json").read_text())
    review = json.loads((artifacts / "review.json").read_text())
    promotion = json.loads((artifacts / "promotion.json").read_text())
    persistence = json.loads((artifacts / "persistence.json").read_text())
    snapshot = json.loads((artifacts / "snapshot.json").read_text())
    synthesis = json.loads((artifacts / "synthesis.json").read_text())
    export = json.loads((artifacts / "export_receipt.json").read_text())
    note = tmp_path / "demo" / "obsidian-vault" / "TargetIntel" / "DEMO_TARGET.md"

    assert summary["provider"] == "MockProvider" and summary["synthetic_content"]
    assert extraction["accepted_candidates"] and audit["cards"]
    assert review["packet"]["research_only"] and all(x["decision"] == "approve" for x in review["decisions"])
    assert all(x["status"] == "promoted" and x["evidence_item"] for x in promotion["promotions"])
    assert all(x["status"] == "persisted" and x["persisted"] for x in persistence["receipts"])
    assert snapshot["status"] == "created" and snapshot["snapshot"]["snapshot_validation_state"] == "validated"
    assert synthesis["status"] == "generated" and synthesis["synthesis"]["no_score_or_ranking_generated"]
    evidence_id_by_direction = {
        promotion_result["evidence_item"]["evidence_direction"]: promotion_result["evidence_item_id"]
        for promotion_result in promotion["promotions"]
    }
    statement_by_key = {
        statement["local_statement_key"]: statement
        for statement in synthesis["synthesis"]["statements"]
    }
    assert statement_by_key["support"]["evidence_item_ids"] == [evidence_id_by_direction["supports_target"]]
    assert statement_by_key["contradiction"]["evidence_item_ids"] == [evidence_id_by_direction["contradicts_target"]]
    assert statement_by_key["limit"]["evidence_item_ids"] == [evidence_id_by_direction["limits_target"]]
    text = note.read_text()
    assert "Limitation:" in text and "no significant difference" in text and "[evidence:" in text
    assert export["first"]["status"] == "written" and export["second"]["status"] == "already_current"
    assert hashlib.sha256(note.read_bytes()).hexdigest() == export["plan"]["content_sha256"]
    assert all(summary["identities"].values())


def test_v030_demo_scientific_identities_ignore_operational_output_path(tmp_path: Path) -> None:
    first = _run(tmp_path / "one")
    second = _run(tmp_path / "two")
    assert first["identities"] == second["identities"]


def test_v030_demo_reruns_safely_in_the_same_output_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "demo"
    first = _run(output_dir)
    second = _run(output_dir)
    persistence = json.loads((output_dir / "artifacts" / "persistence.json").read_text())
    export = json.loads((output_dir / "artifacts" / "export_receipt.json").read_text())

    assert first["identities"]["snapshot"] == second["identities"]["snapshot"]
    assert all(receipt["status"] == "already_persisted" for receipt in persistence["receipts"])
    assert export["first"]["status"] == "already_current"
    assert export["second"]["status"] == "already_current"


def test_readme_and_release_state_the_v030_boundaries() -> None:
    readme = (ROOT / "README.md").read_text()
    release = (ROOT / "docs" / "releases" / "v0.3.0.md").read_text()
    assert len(readme.splitlines()) <= 360
    for text in ("examples/llm/README.md", "docs/releases/v0.3.0.md", "mandatory human review", "does not alter deterministic scores, rankings, or role classification"):
        assert text in readme
    for text in ("does not validate targets or biomarkers", "does not rank targets through the LLM layer", "does not change the deterministic scoring pipeline", "not a scientific source of truth"):
        assert text in release
