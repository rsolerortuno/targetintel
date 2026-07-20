"""Offline contract checks for the Issue 506 integration gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from targetintel.functional_dependency import (
    DependencyIntegrationError, DependencyIntegrationPolicy,
    DependencyAwareProfileCandidate, DependencyProfileAuthorization,
    build_dependency_integration, load_baseline_ranking,
    select_dependency_profile, write_dependency_integration_artifacts,
    validate_evidence_scope, validate_integration_state,
)


FIXTURE = Path("tests/fixtures/depmap/integration/integration_policy.json")
BASELINE = Path("tests/fixtures/depmap/benchmark/baseline_ranking.tsv")


def _write_issue505_fixture(directory: Path) -> None:
    """Write the smallest complete, internally compatible Issue 505 bundle."""
    _, baseline_id, fingerprint = load_baseline_ranking(BASELINE)
    (directory / "dependency_benchmark_manifest.json").write_text(json.dumps({
        "freeze_id": "tufm_fixture", "benchmark_universe_id": "tu_fixture",
        "dependency_profile_run_id": "dmpr_fixture", "baseline_ranking_id": baseline_id,
        "baseline_fingerprint": fingerprint, "policy_id": "dmbp_fixture",
        "integration_status": "human_review_required",
        "candidate_ranking_ids": {"dependency_only": "dmbr_dependency", "bounded_overlay": "dmbr_bounded"},
    }))
    (directory / "benchmark_coverage.json").write_text(json.dumps({"total_benchmark_targets": 4, "profiled_target_count": 3}))
    (directory / "candidate_metrics.json").write_text(json.dumps({"rank_stability": [{
        "ranking": "bounded_overlay_rank", "spearman_rank_correlation": 1.0,
        "band_violations": 0, "median_absolute_rank_change": 0,
    }]}))
    (directory / "integration_evidence.json").write_text(json.dumps({"criteria": [{
        "criterion": "minimum_holdout_coverage", "observed": 0.5,
    }]}))
    (directory / "partition_metrics.tsv").write_text(
        "partition\tranking\tk\teligible_target_count\trecall_at_k\tnegative_top_k_count\n"
        "combined\tbaseline_rank\t1\t2\t1.0\t0\n"
        "combined\tbounded_overlay_rank\t1\t2\t1.0\t0\n"
    )
    (directory / "ablation_metrics.tsv").write_text(
        "top_k_jaccard_vs_baseline\n1.0\n"
    )
    (directory / "rank_comparison.tsv").write_text(
        "canonical_identity\tdependency_signal\tcomponent_count\tbounded_overlay_rank\n"
        "symbol:BRAF|entrez:673\t1.0\t1\t1\n"
        "symbol:NRAS|entrez:4893\t0.5\t1\t2\n"
        "symbol:PTEN|entrez:5728\t\t0\t3\n"
    )


def test_integration_policy_identity_is_order_independent_and_threshold_sensitive():
    payload = json.loads(FIXTURE.read_text())
    policy = DependencyIntegrationPolicy.from_dict(payload)
    reordered = {key: payload[key] for key in reversed(list(payload))}
    assert DependencyIntegrationPolicy.from_dict(reordered).policy_id == policy.policy_id
    changed = dict(payload); changed["minimum_benchmark_coverage"] = 0.6
    assert DependencyIntegrationPolicy.from_dict(changed).policy_id != policy.policy_id


def test_controlled_state_and_evidence_scope_reject_unknown_values():
    assert validate_integration_state("blocked_fixture_evidence") == "blocked_fixture_evidence"
    assert validate_evidence_scope("synthetic_fixture") == "synthetic_fixture"
    with pytest.raises(DependencyIntegrationError): validate_integration_state("unknown")
    with pytest.raises(DependencyIntegrationError): validate_evidence_scope("")


def test_policy_rejects_unknown_scope_target_specific_threshold_and_missing_field():
    payload = json.loads(FIXTURE.read_text())
    bad_scope = dict(payload); bad_scope["allowed_evidence_scopes"] = ["invented"]
    with pytest.raises(DependencyIntegrationError): DependencyIntegrationPolicy.from_dict(bad_scope)
    targeted = dict(payload); targeted["target_specific_thresholds"] = {"BRAF": 1}
    with pytest.raises(DependencyIntegrationError): DependencyIntegrationPolicy.from_dict(targeted)
    missing = dict(payload); del missing["primary_k"]
    with pytest.raises(DependencyIntegrationError): DependencyIntegrationPolicy.from_dict(missing)


def test_profile_selection_is_baseline_by_default_and_fails_closed():
    candidate = DependencyAwareProfileCandidate(
        "v0.5.0", "dependency_aware_melanoma_anti_pd1_candidate_v1", "melanoma_anti_pd1:v1",
        "blr_test", "dmpr_test", "dmbr_test", "dmip_test", "bounded_overlay", 2,
        "midrank_signal_baseline_then_identity", 1, "retain_baseline_order",
        "dependency_aware_melanoma_anti_pd1_candidate_v1", "blocked_fixture_evidence", ["fixture"],
    )
    assert select_dependency_profile(None, candidate) == "baseline"
    with pytest.raises(DependencyIntegrationError): select_dependency_profile("unknown", candidate)
    with pytest.raises(DependencyIntegrationError): select_dependency_profile(candidate.opt_in_name, candidate)


def test_gate_end_to_end_preserves_baseline_blocks_fixture_and_is_byte_equivalent(tmp_path):
    benchmark_dir = tmp_path / "benchmark"; benchmark_dir.mkdir()
    _write_issue505_fixture(benchmark_dir)
    policy = DependencyIntegrationPolicy.from_dict(json.loads(FIXTURE.read_text()))
    context = {"context_identity": "melanoma_anti_pd1:v1"}

    real_result = build_dependency_integration(benchmark_dir, BASELINE, policy, context, "local_real_data")
    assert real_result["decision"]["decision_state"] == "eligible_for_human_activation"
    assert all(row["result"] == "pass" for row in real_result["criteria"])
    assert real_result["candidate"].candidate_status == "eligible_for_human_activation"
    assert real_result["preservation"]["baseline_file_bytes_unchanged"]
    assert [row["candidate_rank"] for row in real_result["overlay"]] == [1, 2, 3, 4]

    authorization = DependencyProfileAuthorization(
        real_result["candidate"].candidate_id, "real_benchmark_v1",
        real_result["decision"]["decision_id"], context["context_identity"],
        "review-1", "approved", ["Future real-data authorization."],
    )
    assert select_dependency_profile(real_result["candidate"].opt_in_name, real_result["candidate"], authorization) == real_result["candidate"].opt_in_name
    with pytest.raises(DependencyIntegrationError):
        DependencyProfileAuthorization("candidate", "fixture_benchmark", "decision", "context", "review", "approved", [])

    first = tmp_path / "first"; second = tmp_path / "second"
    write_dependency_integration_artifacts(first, real_result)
    write_dependency_integration_artifacts(second, real_result)
    assert sorted(path.name for path in first.iterdir()) == [
        "activation_readiness.json", "baseline_preservation.json", "candidate_overlay.tsv",
        "dependency_aware_profile_candidate.json", "dependency_integration_manifest.json",
        "input_compatibility.json", "integration_criteria.tsv", "integration_gate_decision.json",
        "integration_report.md",
    ]
    assert {path.name: path.read_bytes() for path in first.iterdir()} == {path.name: path.read_bytes() for path in second.iterdir()}

    fixture_result = build_dependency_integration(benchmark_dir, BASELINE, policy, context, "synthetic_fixture")
    assert fixture_result["decision"]["decision_state"] == "blocked_fixture_evidence"
    assert fixture_result["decision"]["human_review_required"] is True
    assert fixture_result["decision"]["production_activation_enabled"] is False


def test_gate_rejects_overlay_recipe_divergence(tmp_path):
    benchmark_dir = tmp_path / "benchmark"; benchmark_dir.mkdir()
    _write_issue505_fixture(benchmark_dir)
    ranks = benchmark_dir / "rank_comparison.tsv"
    ranks.write_text(ranks.read_text().replace("symbol:NRAS|entrez:4893\t0.5\t1\t2", "symbol:NRAS|entrez:4893\t0.5\t1\t1"))
    policy = DependencyIntegrationPolicy.from_dict(json.loads(FIXTURE.read_text()))
    result = build_dependency_integration(benchmark_dir, BASELINE, policy, {"context_identity": "melanoma_anti_pd1:v1"}, "local_real_data")
    assert result["decision"]["decision_state"] == "blocked_incompatible_inputs"
    assert "bounded_overlay_recipe_mismatch" in result["compatibility"]["reasons"]
