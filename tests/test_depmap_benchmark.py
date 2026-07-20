"""Offline contracts for the Issue 505 analysis-only benchmark."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from targetintel.functional_dependency.depmap_benchmark import (
    _hypergeometric_tail,
    _integration_evidence,
    _metrics,
    _percentiles,
    _rank,
    _signal,
    _stability,
)
from targetintel.functional_dependency import (
    DependencyBenchmarkError, DependencyBenchmarkPolicy,
    DepMapIngestionRequest, DepMapModelContextDefinition,
    DepMapReleaseManifest, DepMapTargetRequest,
    FunctionalDependencyProfilePolicy, build_dependency_profiles,
    evaluate_dependency_benchmark, load_baseline_ranking,
    freeze_universes, ingest_local_release,
    write_dependency_benchmark_artifacts,
    write_dependency_profile_artifacts,
)


ROOT = Path("tests/fixtures/depmap")


def policy() -> DependencyBenchmarkPolicy:
    return DependencyBenchmarkPolicy.from_dict(json.loads((ROOT / "benchmark/evaluation_policy.json").read_text()))


def test_policy_identity_is_order_independent_and_threshold_sensitive() -> None:
    first = policy()
    payload = first.to_dict()
    payload["positive_classes"] = list(reversed(payload["positive_classes"]))
    assert DependencyBenchmarkPolicy.from_dict(payload).policy_id == first.policy_id
    payload["minimum_benchmark_coverage"] = .6
    payload.pop("policy_id", None)
    assert DependencyBenchmarkPolicy.from_dict(payload).policy_id != first.policy_id


def test_baseline_contract_rejects_duplicate_and_invalid_ranks(tmp_path: Path) -> None:
    source = ROOT / "benchmark/baseline_ranking.tsv"
    rows, identity, fingerprint = load_baseline_ranking(source)
    assert len(rows) == 4 and identity.startswith("blr_") and len(fingerprint) == 64
    duplicate = tmp_path / "duplicate.tsv"
    duplicate.write_text(source.read_text().replace("NRAS\tsymbol:NRAS|entrez:4893", "NRAS\tsymbol:BRAF|entrez:673"), encoding="utf-8")
    with pytest.raises(DependencyBenchmarkError, match="duplicate"):
        load_baseline_ranking(duplicate)
    invalid = tmp_path / "invalid.tsv"
    invalid.write_text(source.read_text().replace("\t1\t0.9", "\t0\t0.9", 1), encoding="utf-8")
    with pytest.raises(DependencyBenchmarkError, match="positive"):
        load_baseline_ranking(invalid)


def test_fixture_evaluation_requires_artifacts_and_preserves_labels(tmp_path: Path) -> None:
    # The fixture test only checks fail-closed identity requirements; the
    # operational chain is exercised by the example test below.
    with pytest.raises(DependencyBenchmarkError, match="universe_freeze_manifest"):
        evaluate_dependency_benchmark(tmp_path, tmp_path, ROOT / "benchmark/baseline_ranking.tsv", policy())


def _row(
    identity: str,
    benchmark_class: str,
    baseline_rank: int | None,
    signal: float | None,
    partition: str = "development",
) -> dict[str, object]:
    return {
        "canonical_identity": identity,
        "benchmark_class": benchmark_class,
        "baseline_rank": baseline_rank,
        "dependency_signal": signal,
        "partition": partition,
    }


def test_metric_denominators_and_exact_enrichment_are_deterministic() -> None:
    rows = [
        _row("positive-first", "known_positive", 1, .3),
        _row("negative", "negative_control", 2, .2),
        _row("positive-last", "known_positive", 3, .1),
        _row("descriptive", "challenging_control", 4, .0),
    ]
    metrics = _metrics(rows, "development", "baseline_rank", policy())
    at_two = next(item for item in metrics if item["k"] == 2)
    assert at_two["eligible_target_count"] == 3
    assert at_two["ranked_target_count"] == 3
    assert at_two["positive_count"] == 2
    assert at_two["negative_count"] == 1
    assert at_two["recall_at_k"] == pytest.approx(.5)
    assert at_two["precision_at_k"] == pytest.approx(.5)
    assert at_two["average_precision"] == pytest.approx(5 / 6)
    assert at_two["mean_reciprocal_rank"] == pytest.approx(1.0)
    assert at_two["median_rank"] == pytest.approx(2.0)
    assert at_two["normalized_median_rank"] == pytest.approx(2 / 3)
    assert at_two["negative_exclusion_outside_top_k"] == pytest.approx(0.0)
    assert _hypergeometric_tail(3, 2, 2, 1) == pytest.approx(1.0)
    assert _hypergeometric_tail(2, 3, 1, 1) is None


def test_metrics_retain_missing_positive_controls_without_rank_reduction_errors() -> None:
    rows = [
        _row("ranked-positive", "known_positive", 1, .3),
        _row("unranked-positive", "known_positive", None, None),
        _row("negative", "negative_control", 2, .2),
    ]

    metrics = _metrics(rows, "development", "dependency_only_rank", policy())
    at_two = next(item for item in metrics if item["k"] == 2)

    assert at_two["positive_count"] == 2
    assert at_two["ranked_target_count"] == 0
    assert at_two["mean_reciprocal_rank"] is None
    assert at_two["median_rank"] is None
    assert at_two["normalized_median_rank"] is None

    rows[0]["dependency_only_rank"] = 1
    rows[2]["dependency_only_rank"] = 2
    metrics = _metrics(rows, "development", "dependency_only_rank", policy())
    at_two = next(item for item in metrics if item["k"] == 2)
    assert at_two["positive_count"] == 2
    assert at_two["ranked_target_count"] == 2
    assert at_two["mean_reciprocal_rank"] == pytest.approx(1.0)
    assert at_two["median_rank"] == pytest.approx(1.0)
    assert at_two["normalized_median_rank"] == pytest.approx(.5)


def test_signal_direction_percentiles_ties_and_missing_components_are_explicit() -> None:
    rows = [
        {"canonical_identity": "strong", "profile": {"payload": {"contrasts": {"gene_effect_context_minus_non_context_median": -.5, "dependency_probability_context_minus_non_context_median": .4}, "empirical_context_lineage_position": {"value": .8}}}},
        {"canonical_identity": "tied", "profile": {"payload": {"contrasts": {"gene_effect_context_minus_non_context_median": -.5, "dependency_probability_context_minus_non_context_median": .2}, "empirical_context_lineage_position": {"value": .4}}}},
        {"canonical_identity": "missing", "profile": {"payload": {"contrasts": {"gene_effect_context_minus_non_context_median": None, "dependency_probability_context_minus_non_context_median": None}, "empirical_context_lineage_position": {"value": None}}}},
    ]
    _signal(rows, ("gene_effect_contrast", "dependency_probability_contrast", "lineage_position"), 2)
    assert rows[0]["dependency_signal"] > rows[1]["dependency_signal"]
    assert rows[2]["dependency_signal"] is None
    assert rows[2]["ineligible_reason"] == "insufficient_dependency_components"
    assert _percentiles({"a": 1.0, "b": 1.0}) == {"a": .5, "b": .5}


def test_diagnostic_and_bounded_ranks_preserve_baseline_contracts() -> None:
    rows = [
        _row("a", "known_positive", 1, .1),
        _row("b", "negative_control", 2, .9),
        _row("c", "known_positive", 3, None),
        _row("d", "negative_control", 4, .8),
    ]
    _rank(rows, "dependency_only_rank", overlay=False)
    _rank(rows, "bounded_overlay_rank", overlay=True, band_size=2)
    assert [row["dependency_only_rank"] for row in rows] == [3, 1, 4, 2]
    assert [row["baseline_rank"] for row in rows] == [1, 2, 3, 4]
    assert [row["bounded_overlay_rank"] for row in rows] == [2, 1, 3, 4]
    stability = _stability(rows, "bounded_overlay_rank", 2, band_size=2)
    assert stability["band_violations"] == 0
    assert stability["top_k_jaccard"] == pytest.approx(1.0)
    assert stability["median_absolute_rank_change"] == pytest.approx(.5)


def test_bounded_overlay_uses_numeric_baseline_bands_for_gapped_subset() -> None:
    """A benchmark subset must not redefine bands from its own row positions."""
    rows = [
        _row("early", "known_positive", 5, .2),
        _row("same-band-low", "negative_control", 42, .1),
        _row("same-band-high", "known_positive", 47, .9),
        _row("later", "negative_control", 132, .8),
    ]

    _rank(rows, "bounded_overlay_rank", overlay=True, band_size=50)

    assert [row["bounded_overlay_rank"] for row in rows] == [42, 47, 5, 132]
    stability = _stability(rows, "bounded_overlay_rank", 2, band_size=50)
    assert stability["band_violations"] == 0


def test_holdout_integration_coverage_is_partitioned_and_has_a_status() -> None:
    rows = [
        {"partition": "development", "profile": object()},
        {"partition": "development", "profile": None},
        {"partition": "holdout", "profile": object()},
        {"partition": "holdout", "profile": None},
        {"partition": "holdout", "profile": None},
    ]
    evidence = _integration_evidence(rows, {"band_violations": 0}, policy())
    holdout = next(item for item in evidence["criteria"] if item["criterion"] == "minimum_holdout_coverage")
    assert holdout == {
        "criterion": "minimum_holdout_coverage",
        "observed": pytest.approx(1 / 3),
        "threshold": .5,
        "numerator": 1,
        "denominator": 3,
        "status": "fail",
    }
    unavailable = _integration_evidence([], {"band_violations": 0}, policy())
    assert unavailable["criteria"][1]["status"] == "unavailable"


def test_synthetic_operational_artifacts_cover_reconciliation_and_ablations(
    tmp_path: Path,
) -> None:
    """The compact fixture fixes quantitative outputs without scientific claims."""
    ingestion_source = ROOT / "ingestion"
    manifest = DepMapReleaseManifest.from_dict(
        json.loads((ingestion_source / "release_manifest.json").read_text())
    )
    ingestion_dir = (tmp_path / "ingestion").resolve()
    ingest_local_release(
        DepMapIngestionRequest(
            "v0.5.0", manifest, "target_subset", ingestion_source.resolve(),
            ingestion_dir,
            target_universe=[
                DepMapTargetRequest(symbol, "symbol")
                for symbol in ("BRAF", "CDK4", "NRAS", "NONE")
            ],
        )
    )
    universe_dir = (tmp_path / "universe").resolve()
    benchmark_source = tmp_path / "benchmark.tsv"
    benchmark_source.write_text(
        (ROOT / "universes/benchmark.tsv").read_text(encoding="utf-8")
        + "NONE\tunresolved:NONE\tnegative_control\ttumor_intrinsic_driver\t"
        "synthetic profiled-only reconciliation control\tmechanism\tinternal:benchmark-v1\t"
        "Synthetic test-only entry.\tholdout\tv1\tSynthetic fixture\n",
        encoding="utf-8",
    )
    freeze_universes(
        benchmark_source,
        ROOT / "universes/discovery_sources.tsv",
        ROOT / "universes/discovery_policy.json",
        ingestion_dir / "gene_index.tsv",
        json.loads((ROOT / "universes/context.json").read_text()),
        universe_dir,
    )
    context = DepMapModelContextDefinition.from_dict(
        json.loads((ROOT / "profiles/melanoma_context.json").read_text())
    )
    profile_policy = FunctionalDependencyProfilePolicy.from_dict(
        json.loads((ROOT / "profiles/profile_policy.json").read_text())
    )
    profile_run, assignments = build_dependency_profiles(
        ingestion_dir, context, profile_policy
    )
    profiles_dir = (tmp_path / "profiles").resolve()
    write_dependency_profile_artifacts(profiles_dir, profile_run, assignments)

    baseline = ROOT / "benchmark/baseline_ranking.tsv"
    before = baseline.read_bytes()
    evaluation = evaluate_dependency_benchmark(
        universe_dir, profiles_dir, baseline, policy()
    )
    assert baseline.read_bytes() == before
    rows = {row["original_identifier"]: row for row in evaluation.rows}
    assert rows["BRAF"]["reconciliation_state"] == "ranked_and_profiled"
    assert rows["PTEN"]["reconciliation_state"] == "ranked_not_profiled"
    assert rows["TP53"]["reconciliation_state"] == "unresolved_benchmark_target"
    assert rows["NONE"]["reconciliation_state"] == "profiled_not_ranked"
    assert rows["PTEN"]["dependency_only_rank"] is not None
    assert rows["TP53"]["dependency_only_rank"] is None

    output_dir = (tmp_path / "benchmark").resolve()
    write_dependency_benchmark_artifacts(output_dir, evaluation, policy())
    ablations = (output_dir / "ablation_metrics.tsv").read_text(encoding="utf-8")
    for name in policy().source_ablations:
        assert name in ablations
    candidates = json.loads((output_dir / "candidate_metrics.json").read_text())
    assert candidates["rank_stability"][1]["band_violations"] == 0
    integration = json.loads((output_dir / "integration_evidence.json").read_text())
    holdout = next(
        item for item in integration["criteria"]
        if item["criterion"] == "minimum_holdout_coverage"
    )
    assert holdout["numerator"] == 2
    assert holdout["denominator"] == 3
    assert holdout["observed"] == pytest.approx(2 / 3)
    assert holdout["status"] == "pass"
