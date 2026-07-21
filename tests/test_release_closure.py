"""Offline checks for the v0.5.0 release-closure boundary."""
from __future__ import annotations
import csv
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import pytest
from targetintel.functional_dependency import (ReleaseClosureError,
    V050ReleaseClosurePolicy, V050ReleaseRunConfiguration, compare_release_runs,
    preflight_release, run_release_closure, validate_evidence_classification,
    validate_release_state)
from targetintel.functional_dependency.release_closure import (
    _criterion, _release_state_before_reproducibility, _safe_nested,
)

ROOT = Path("tests/fixtures/depmap/release_closure")

def config() -> V050ReleaseRunConfiguration:
    return V050ReleaseRunConfiguration.from_file(ROOT / "run_config.json")

def test_controlled_release_enums_fail_closed() -> None:
    assert validate_release_state("blocked_fixture_evidence") == "blocked_fixture_evidence"
    assert validate_evidence_classification("synthetic_fixture") == "synthetic_fixture"
    with pytest.raises(ReleaseClosureError): validate_release_state("ready")
    with pytest.raises(ReleaseClosureError): validate_evidence_classification("real")

def test_config_identity_is_path_independent_and_checksum_sensitive(tmp_path: Path) -> None:
    first = config(); copied = tmp_path / "config.json"; copied.write_text((ROOT / "run_config.json").read_text())
    # Relative paths intentionally point elsewhere and are therefore unsuitable;
    # identity itself is derived from bytes, not the configuration filename.
    assert first.configuration_id == config().configuration_id
    data = json.loads((ROOT / "run_config.json").read_text()); data["limitations"].append("changed")
    changed = tmp_path / "changed.json"; changed.write_text(json.dumps(data))
    assert V050ReleaseRunConfiguration.from_file(changed).configuration_id != first.configuration_id


def test_run_configuration_rejects_url_reference(tmp_path: Path) -> None:
    payload = json.loads((ROOT / "run_config.json").read_text())
    payload["release_manifest"] = "https://example.invalid/release_manifest.json"
    path = tmp_path / "url-config.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ReleaseClosureError, match="local file references"):
        V050ReleaseRunConfiguration.from_file(path)

def test_fixture_preflight_and_closure_are_blocked_but_complete(tmp_path: Path) -> None:
    result = run_release_closure(config(), "synthetic_fixture", tmp_path / "one")
    assert result["terminal_state"] == "blocked_fixture_evidence"
    assert not result["successful_closure"]
    for name in ("release_preflight.json", "stage_manifest_index.json", "release_criteria.tsv", "release_readiness.json", "activation_readiness_summary.json", "human_release_actions.json"):
        assert (tmp_path / "one" / name).is_file()
    activation = json.loads((tmp_path / "one" / "activation_readiness_summary.json").read_text())
    assert activation["candidate_activation_readiness"] == "blocked"
    assert activation["approved_authorization_emitted"] is False


def test_closure_retains_unchanged_baseline_bytes_fingerprint_ranks_and_scores(tmp_path: Path) -> None:
    baseline = config().references["baseline_ranking"]
    baseline_bytes = baseline.read_bytes()
    baseline_rows = list(csv.DictReader(baseline.open(encoding="utf-8", newline=""), delimiter="\t"))
    run_release_closure(config(), "synthetic_fixture", tmp_path / "closure")

    preservation = json.loads((tmp_path / "closure" / "integration" / "baseline_preservation.json").read_text())
    benchmark_manifest = json.loads((tmp_path / "closure" / "benchmark" / "dependency_benchmark_manifest.json").read_text())
    overlay_rows = list(csv.DictReader((tmp_path / "closure" / "integration" / "candidate_overlay.tsv").open(encoding="utf-8", newline=""), delimiter="\t"))
    assert baseline.read_bytes() == baseline_bytes
    assert preservation["baseline_file_bytes_unchanged"] is True
    assert preservation["baseline_fingerprint_before"] == preservation["baseline_fingerprint_after"] == sha256(baseline_bytes).hexdigest()
    assert benchmark_manifest["baseline_fingerprint"] == preservation["baseline_fingerprint_before"]
    assert preservation["baseline_ranks_retained_exactly"] is True
    assert preservation["baseline_scores_retained_exactly"] is True
    assert [(row["canonical_target_identity"], row["baseline_rank"], row["baseline_score"]) for row in overlay_rows] == [
        (row["canonical_target_identity"], row["baseline_rank"], row["baseline_score"])
        for row in baseline_rows
    ]

def test_fixture_cannot_be_relabelled_real(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "run_config.json").read_text())
    raw["evidence_classification"] = "local_real_public_release"
    for key, value in list(raw.items()):
        if key not in {"configuration_format_version", "evidence_classification", "expected_context_identity", "limitations"}:
            raw[key] = str(config().references[key])
    path = tmp_path / "real-label.json"; path.write_text(json.dumps(raw))
    result = run_release_closure(V050ReleaseRunConfiguration.from_file(path), "local_real_public_release", tmp_path / "bad")
    assert result["terminal_state"] == "blocked_invalid_real_data"

def test_policy_identity_changes_with_threshold() -> None:
    first = V050ReleaseClosurePolicy.from_file(ROOT / "release_policy.json")
    payload = json.loads((ROOT / "release_policy.json").read_text()); payload["minimum_benchmark_count"] = 5
    changed = ROOT / "policy-copy.json"
    try:
        changed.write_text(json.dumps(payload)); assert V050ReleaseClosurePolicy.from_file(changed).policy_id != first.policy_id
    finally:
        changed.unlink(missing_ok=True)

def test_equivalent_fixture_runs_compare_reproducible(tmp_path: Path) -> None:
    run_release_closure(config(), "synthetic_fixture", tmp_path / "one")
    run_release_closure(config(), "synthetic_fixture", tmp_path / "two")
    assert compare_release_runs(tmp_path / "one", tmp_path / "two")["result"] == "reproducible"


def test_reproducibility_comparison_detects_nested_scientific_artifact_change(tmp_path: Path) -> None:
    run_release_closure(config(), "synthetic_fixture", tmp_path / "one")
    run_release_closure(config(), "synthetic_fixture", tmp_path / "two")
    artifact = tmp_path / "two" / "integration" / "integration_gate_decision.json"
    artifact.write_text(artifact.read_text() + "\n")
    comparison = compare_release_runs(tmp_path / "one", tmp_path / "two")
    assert comparison["result"] == "nonreproducible"
    assert "integration/integration_gate_decision.json" in comparison["differing_artifacts"]


def test_reproducibility_comparison_detects_top_level_scientific_artifact_change(tmp_path: Path) -> None:
    run_release_closure(config(), "synthetic_fixture", tmp_path / "one")
    run_release_closure(config(), "synthetic_fixture", tmp_path / "two")
    artifact = tmp_path / "two" / "release_readiness.json"
    artifact.write_text(artifact.read_text() + "\n")
    comparison = compare_release_runs(tmp_path / "one", tmp_path / "two")
    assert comparison["result"] == "nonreproducible"
    assert "release_readiness.json" in comparison["differing_artifacts"]
    assert "output_checksums.tsv" in comparison["excluded_artifacts"]


def test_module_can_be_ready_when_reproducibility_has_been_verified_despite_blocked_candidate() -> None:
    policy = V050ReleaseClosurePolicy.from_file(ROOT / "release_policy.json")
    criteria = [{"criterion_id": "benchmark_count", "mandatory": True, "result": "pass"}]
    assert _release_state_before_reproducibility(
        policy, "local_real_public_release", criteria, {"decision_state": "blocked_insufficient_evidence"},
    ) == "ready_research_preview_human_review"


def test_incompatible_issue506_artifacts_block_module_readiness() -> None:
    policy = V050ReleaseClosurePolicy.from_file(ROOT / "release_policy.json")
    criteria = [{"criterion_id": "integration_artifact_compatibility", "mandatory": True, "result": "fail"}]
    assert _release_state_before_reproducibility(
        policy, "local_real_public_release", criteria, {"decision_state": "blocked_incompatible_inputs"},
    ) == "blocked_incompatible_artifacts"


def test_unavailable_mandatory_criterion_is_not_a_pass_or_ready_state() -> None:
    policy = V050ReleaseClosurePolicy.from_file(ROOT / "release_policy.json")
    unavailable = _criterion(
        "holdout_coverage", "Holdout coverage is unavailable.", "integration_evidence.json",
        "minimum_holdout_coverage", None, ">=", policy.minimum_holdout_coverage,
    )
    assert unavailable["result"] == "unavailable"
    assert _release_state_before_reproducibility(
        policy, "local_real_public_release", [unavailable], {"decision_state": "blocked_insufficient_evidence"},
    ) == "blocked_benchmark_failure"


def test_integration_context_rejects_nested_credential_fields(tmp_path: Path) -> None:
    unsafe_context = tmp_path / "integration-context.json"
    unsafe_context.write_text(json.dumps({"context_identity": "melanoma_anti_pd1:v1", "nested": {"token": "not-permitted"}}))
    unsafe_config = replace(config(), references={**config().references, "integration_context": unsafe_context})
    run_release_closure(unsafe_config, "synthetic_fixture", tmp_path / "closure")
    compatibility = json.loads((tmp_path / "closure" / "artifact_compatibility.json").read_text())
    assert "integration context contains controlled credential" in compatibility["metrics"]["failure"]


def test_nested_scalar_secrets_are_rejected_but_authorization_prose_is_allowed() -> None:
    assert not _safe_nested({"nested": "Authorization: Bearer secret-value"})
    assert not _safe_nested(["password=hunter2", "api_key=secret", "-----BEGIN PRIVATE KEY-----"])
    assert not _safe_nested({"nested": {"hidden_reasoning": "not retained"}})
    assert _safe_nested({"limitation": "Human authorization required at the activation authorization boundary."})


def test_relative_traversal_is_rejected_and_absolute_local_reference_is_permitted(tmp_path: Path) -> None:
    raw = json.loads((ROOT / "run_config.json").read_text())
    raw["benchmark"] = "../outside.tsv"
    escaped = tmp_path / "escaped.json"; escaped.write_text(json.dumps(raw))
    with pytest.raises(ReleaseClosureError, match="escapes"):
        V050ReleaseRunConfiguration.from_file(escaped)
    raw = json.loads((ROOT / "run_config.json").read_text())
    raw["benchmark"] = str(config().references["benchmark"])
    for key in config().references:
        raw[key] = str(config().references[key])
    absolute = tmp_path / "absolute.json"; absolute.write_text(json.dumps(raw))
    assert V050ReleaseRunConfiguration.from_file(absolute).references["benchmark"] == config().references["benchmark"]


def test_malformed_manifest_is_a_sanitized_preflight_failure(tmp_path: Path) -> None:
    malformed = tmp_path / "manifest.json"
    payload = json.loads(config().references["release_manifest"].read_text())
    payload["release_limitations"] = 3
    malformed.write_text(json.dumps(payload))
    altered = replace(config(), references={**config().references, "release_manifest": malformed})
    result = preflight_release(altered, "synthetic_fixture")
    assert result["status"] == "failed"
    assert result["failures"] == ["release manifest is invalid"]


def test_missing_real_data_is_blocked_without_a_successful_closure(tmp_path: Path) -> None:
    real = replace(config(), evidence_classification="local_real_public_release", references={**config().references, "data_root": tmp_path / "missing"})
    result = run_release_closure(real, "local_real_public_release", tmp_path / "closure")
    assert result["terminal_state"] == "blocked_missing_real_data"
    assert result["successful_closure"] is False


def test_preflight_rejects_missing_required_input_and_manifest_checksum_mismatch(tmp_path: Path) -> None:
    missing = replace(config(), references={**config().references, "target_subset": tmp_path / "missing.tsv"})
    assert preflight_release(missing, "synthetic_fixture")["status"] == "failed"
    copied_root = tmp_path / "ingestion"
    shutil.copytree(config().references["data_root"], copied_root)
    source = copied_root / "gene_effect.csv"
    source.write_text(source.read_text() + "\n")
    mismatched = replace(config(), references={**config().references, "data_root": copied_root})
    result = preflight_release(mismatched, "synthetic_fixture")
    assert result["status"] == "failed"
    assert "release manifest local-file validation failed" in result["failures"]


def test_fixture_runtime_failure_retains_fixture_terminal_state(tmp_path: Path) -> None:
    unsafe_context = tmp_path / "integration-context.json"
    unsafe_context.write_text(json.dumps({"context_identity": "melanoma_anti_pd1:v1", "nested": {"token": "not-permitted"}}))
    result = run_release_closure(replace(config(), references={**config().references, "integration_context": unsafe_context}), "synthetic_fixture", tmp_path / "closure")
    assert result["terminal_state"] == "blocked_fixture_evidence"
    assert result["successful_closure"] is False
    compatibility = json.loads((tmp_path / "closure" / "artifact_compatibility.json").read_text())
    assert compatibility["metrics"]["failure_category"] == "pipeline_execution_failure"


def test_output_checksums_cover_all_non_self_referential_release_artifacts(tmp_path: Path) -> None:
    run_release_closure(config(), "synthetic_fixture", tmp_path / "closure")
    names = {row["name"] for row in csv.DictReader((tmp_path / "closure" / "output_checksums.tsv").open(), delimiter="\t")}
    assert {"release_readiness.json", "activation_readiness_summary.json", "limitations.tsv", "human_release_actions.json", "release_report.md"} <= names
