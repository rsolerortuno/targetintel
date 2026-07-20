"""Static isolation checks for Issue 506's optional boundary."""
from pathlib import Path


def test_dependency_integration_has_no_production_or_operational_imports():
    text = Path("targetintel/functional_dependency/dependency_integration.py").read_text()
    forbidden = ("targetintel.scoring", "targetintel.intent_ranking", "targetintel.role_classifier", "targetintel.feature_table", "subprocess", "requests", "urllib", "importlib", "eval(")
    assert not any(marker in text for marker in forbidden)


def test_integration_example_does_not_modify_global_cli():
    assert "dependency_integration" not in Path("targetintel/cli.py").read_text()
