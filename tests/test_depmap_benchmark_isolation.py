"""Static isolation guards for Issue 505's analysis-only module."""
from pathlib import Path


def test_dependency_benchmark_does_not_import_production_ranking_surfaces() -> None:
    text = Path("targetintel/functional_dependency/depmap_benchmark.py").read_text(encoding="utf-8")
    for forbidden in ("targetintel.scoring", "targetintel.intent_ranking", "targetintel.role_classifier", "targetintel.feature_table", "subprocess", "requests", "eval(", "importlib"):
        assert forbidden not in text


def test_no_production_score_or_rank_is_mutated() -> None:
    text = Path("targetintel/functional_dependency/depmap_benchmark.py").read_text(encoding="utf-8")
    assert 'baseline_score"] =' not in text
    assert 'baseline_rank"] =' not in text
