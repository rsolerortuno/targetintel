"""Issue 502 remains isolated from scientific scoring and remote mechanisms."""
from pathlib import Path


def test_ingestion_surface_has_no_pipeline_or_remote_dependencies() -> None:
    root = Path(__file__).parents[1] / "targetintel" / "functional_dependency"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in ("targetintel.scoring", "targetintel.intent_ranking", "targetintel.role_classifier", "targetintel.feature_table", "targetintel.modality", "targetintel.opentargets", "targetintel.llm", "requests", "urllib.request", "subprocess", "importlib", "eval("):
        assert forbidden not in source
