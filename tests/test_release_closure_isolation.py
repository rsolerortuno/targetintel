"""Source-level isolation checks for release closure."""
from pathlib import Path

def test_release_closure_has_no_network_subprocess_or_dynamic_execution() -> None:
    source = Path("targetintel/functional_dependency/release_closure.py").read_text()
    for forbidden in ("subprocess", "requests.", "urllib.request", "eval(", "exec(", "importlib"):
        assert forbidden not in source

def test_example_uses_module_api_not_subprocess() -> None:
    source = Path("examples/depmap/run_v0_5_release_closure.py").read_text()
    assert "run_release_closure" in source and "subprocess" not in source
