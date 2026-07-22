from __future__ import annotations
import csv
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from targetintel.functional_dependency.report_snapshot import DepMapReportSnapshotError, export_depmap_report_snapshot

FIXTURE = Path("tests/fixtures/depmap/report_snapshot")

def copied(tmp_path: Path) -> tuple[Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = tmp_path / "fixture"; shutil.copytree(FIXTURE, root)
    return root / "run", root / "config", root / "manifests"

def export(tmp_path: Path, **kwargs: object) -> Path:
    run, config, manifests = copied(tmp_path)
    destination = tmp_path / "snapshot"
    export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=destination, selected_targets=("BRAF", "MISSING"), **kwargs)
    return destination

def tree_bytes(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

def mutate_json(root: Path, relative: str, **changes: object) -> None:
    path = root / relative
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")

def assert_rejected(tmp_path: Path, relative: str, **changes: object) -> None:
    run, config, manifests = copied(tmp_path)
    root = manifests if relative.startswith("manifests/") else run
    mutate_json(root, relative.removeprefix("manifests/"), **changes)
    with pytest.raises(DepMapReportSnapshotError):
        export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=tmp_path / "out")

def test_success_inventory_determinism_checksums_and_missing_profiles(tmp_path: Path) -> None:
    first = export(tmp_path / "one"); second = export(tmp_path / "two")
    expected = {"README.md", "release_summary.json", "release_report.md", "benchmark_report.md", "integration_report.md", "candidate_overlay.tsv", "dependency_profile_summary.tsv", "selected_target_profiles.tsv", "checksums.json"}
    assert {path.name for path in first.iterdir()} == expected
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}
    rows = list(csv.DictReader((first / "selected_target_profiles.tsv").open(), delimiter="\t"))
    assert [row["target"] for row in rows] == ["BRAF", "MISSING"] and rows[1]["coverage_status"] == "not_available"
    checksums = json.loads((first / "checksums.json").read_text())
    assert [item["name"] for item in checksums] == sorted(expected - {"checksums.json"})
    assert all(item["sha256"] == sha256((first / item["name"]).read_bytes()).hexdigest() for item in checksums)

@pytest.mark.parametrize("path, key, value", [("release_preflight.json", "status", "failed"), ("artifact_compatibility.json", "compatible", False), ("release_readiness.json", "release_state", "wrong"), ("reproducibility_summary.json", "result", "nonreproducible")])
def test_invalid_closure_invariants_fail_closed(tmp_path: Path, path: str, key: str, value: object) -> None:
    run, config, manifests = copied(tmp_path); target = run / path; data = json.loads(target.read_text()); data[key] = value; target.write_text(json.dumps(data))
    with pytest.raises(DepMapReportSnapshotError): export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=tmp_path / "out")

def test_identity_activation_paths_and_output_safety(tmp_path: Path) -> None:
    run, config, manifests = copied(tmp_path)
    before = {"run": tree_bytes(run), "config": tree_bytes(config), "manifests": tree_bytes(manifests)}
    with pytest.raises(DepMapReportSnapshotError): export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=run / "nested")
    out = tmp_path / "out"; export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=out)
    with pytest.raises(DepMapReportSnapshotError): export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=out)
    export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=out, overwrite=True)
    assert before == {"run": tree_bytes(run), "config": tree_bytes(config), "manifests": tree_bytes(manifests)}
    assert not any("/home/" in p.read_text() for p in out.iterdir())

def test_configuration_mismatch_and_local_path_leakage_are_rejected(tmp_path: Path) -> None:
    run, config, manifests = copied(tmp_path)
    identity = config / "release_configuration_identity.json"; data = json.loads(identity.read_text()); data["configuration_id"] = "wrong"; identity.write_text(json.dumps(data))
    with pytest.raises(DepMapReportSnapshotError): export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=tmp_path / "bad")
    identity.write_text('{"configuration_id":"v050rc_fixture"}')
    (run / "release_report.md").write_text("path /home/example/private")
    safe = tmp_path / "safe"; export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=safe)
    assert "/home/" not in (safe / "release_report.md").read_text()

def test_cli_matches_module_and_returns_nonzero(tmp_path: Path) -> None:
    run, config, manifests = copied(tmp_path); out = tmp_path / "cli"; direct = tmp_path / "direct"
    command = [sys.executable, "scripts/export_depmap_release_snapshot.py", "--run-dir", str(run), "--config-dir", str(config), "--manifest-dir", str(manifests), "--output-dir", str(out), "--selected-target", "BRAF"]
    assert subprocess.run(command, capture_output=True, text=True).returncode == 0
    assert (out / "selected_target_profiles.tsv").is_file()
    export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=direct, selected_targets=("BRAF",))
    assert tree_bytes(out) == tree_bytes(direct)
    bad = json.loads((run / "release_preflight.json").read_text()); bad["status"] = "failed"; (run / "release_preflight.json").write_text(json.dumps(bad))
    assert subprocess.run(command + ["--overwrite"], capture_output=True, text=True).returncode != 0

@pytest.mark.parametrize(("relative", "changes"), [
    ("release_preflight.json", {"release_manifest_id": "wrong"}),
    ("manifests/real-v6-release-closure-summary.json", {"release_manifest_id": "wrong"}),
    ("manifests/real-v6-run-a-vs-run-b-reproducibility.json", {"release_manifest_id": "wrong"}),
    ("manifests/real-v6-release-closure-summary.json", {"scientific_closure_identity": "wrong"}),
    ("manifests/real-v6-run-a-vs-run-b-reproducibility.json", {"scientific_closure_identity": "wrong"}),
    ("manifests/real-v6-run-a-vs-run-b-reproducibility.json", {"result": "not_reproducible"}),
    ("reproducibility_summary.json", {"differing_artifacts": ["profile"]}),
    ("manifests/real-v6-run-a-vs-run-b-reproducibility.json", {"differing_scientific_artifacts": ["profile"]}),
    ("release_closure_manifest.json", {"successful_closure": False}),
    ("artifact_compatibility.json", {"expected_context_identity": "wrong_context"}),
    ("release_readiness.json", {"human_review_required": False}),
    ("activation_readiness_summary.json", {"human_review_required": False}),
    ("integration/integration_gate_decision.json", {"human_review_required": False}),
    ("integration/activation_readiness.json", {"human_review_required": False}),
    ("activation_readiness_summary.json", {"approved_authorization_emitted": True}),
    ("release_readiness.json", {"production_activation_enabled": True}),
    ("release_closure_manifest.json", {"production_activation_enabled": True}),
    ("integration/integration_gate_decision.json", {"production_activation_enabled": True}),
])
def test_identity_reproducibility_and_activation_invariants_fail_closed(tmp_path: Path, relative: str, changes: dict[str, object]) -> None:
    assert_rejected(tmp_path, relative, **changes)

@pytest.mark.parametrize("key", [
    "baseline_file_bytes_unchanged", "baseline_scores_retained_exactly",
    "baseline_ranks_retained_exactly", "production_scoring_configurations_unchanged",
    "production_ranking_configurations_unchanged",
])
def test_baseline_preservation_invariants_fail_closed(tmp_path: Path, key: str) -> None:
    assert_rejected(tmp_path, "integration/baseline_preservation.json", **{key: False})

def test_dangerous_overwrite_targets_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, config, manifests = copied(tmp_path)
    kwargs = dict(run_dir=run, config_dir=config, manifest_dir=manifests, overwrite=True)
    with pytest.raises(DepMapReportSnapshotError):
        export_depmap_report_snapshot(output_dir=Path.cwd(), **kwargs)
    with pytest.raises(DepMapReportSnapshotError):
        export_depmap_report_snapshot(output_dir=Path("/"), **kwargs)
    link = tmp_path / "output-link"; link.symlink_to(tmp_path / "outside")
    with pytest.raises(DepMapReportSnapshotError):
        export_depmap_report_snapshot(output_dir=link, **kwargs)

def test_profiles_are_streamed_once_and_matrices_are_not_opened(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run, config, manifests = copied(tmp_path)
    profiles = run / "profiles" / "dependency_profiles.jsonl"
    matrix = run / "profiles" / "complete_matrix.csv"; matrix.write_text("must not be opened")
    original_read_text, original_read_bytes, original_open = Path.read_text, Path.read_bytes, Path.open
    def forbid_full_load(path: Path, *args: object, **kwargs: object) -> str:
        if path == profiles:
            raise AssertionError("JSONL must be streamed")
        return original_read_text(path, *args, **kwargs)
    def forbid_profile_bytes(path: Path, *args: object, **kwargs: object) -> bytes:
        if path == profiles:
            raise AssertionError("JSONL must not be copied or loaded")
        return original_read_bytes(path, *args, **kwargs)
    def forbid_matrix(path: Path, *args: object, **kwargs: object):
        if path == matrix:
            raise AssertionError("complete matrices must not be opened")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", forbid_full_load)
    monkeypatch.setattr(Path, "read_bytes", forbid_profile_bytes)
    monkeypatch.setattr(Path, "open", forbid_matrix)
    output = tmp_path / "snapshot"
    export_depmap_report_snapshot(run_dir=run, config_dir=config, manifest_dir=manifests, output_dir=output, selected_targets=("BRAF",))
    assert not (output / profiles.name).exists()
