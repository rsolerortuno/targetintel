"""Offline tests for local, deterministic DepMap ingestion."""
from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from examples.depmap.run_local_ingestion import main as run_local_ingestion
from targetintel.functional_dependency import (
    DepMapIngestionError, DepMapIngestionRequest, DepMapReleaseManifest,
    DepMapTargetRequest, ingest_local_release,
)
from targetintel.functional_dependency.depmap_ingestion import (
    INGESTION_REQUEST_FORMAT_VERSION, parse_gene_label,
)


FIXTURE = Path(__file__).parent / "fixtures" / "depmap" / "ingestion"


def manifest() -> DepMapReleaseManifest:
    return DepMapReleaseManifest.from_dict(json.loads((FIXTURE / "release_manifest.json").read_text()))


def request(tmp_path: Path, mode: str = "target_subset", targets=None) -> DepMapIngestionRequest:
    if targets is None and mode == "target_subset":
        targets = [DepMapTargetRequest("BRAF", "symbol"), DepMapTargetRequest("4893", "entrez"), DepMapTargetRequest("NONE", "symbol")]
    return DepMapIngestionRequest(INGESTION_REQUEST_FORMAT_VERSION, manifest(), mode, FIXTURE.resolve(), (tmp_path / "out").resolve(), target_universe=targets)


def copied_fixture(tmp_path: Path) -> Path:
    destination = tmp_path / "source"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(FIXTURE, destination)
    return destination


def manifest_for(source: Path, changes: dict[str, str] | None = None) -> DepMapReleaseManifest:
    payload = json.loads((FIXTURE / "release_manifest.json").read_text())
    for file_manifest in payload["file_manifests"]:
        filename = file_manifest["relative_filename"]
        if changes and filename in changes:
            (source / filename).write_text(changes[filename], encoding="utf-8", newline="")
        content = (source / filename).read_bytes()
        file_manifest["expected_size_bytes"] = len(content)
        file_manifest["sha256_checksum"] = sha256(content).hexdigest()
    return DepMapReleaseManifest.from_dict(payload)


def source_request(tmp_path: Path, source: Path, *, mode: str = "full_matrix", targets=None, release=None) -> DepMapIngestionRequest:
    return DepMapIngestionRequest(INGESTION_REQUEST_FORMAT_VERSION, release or manifest_for(source), mode,
                                  source.resolve(), (tmp_path / "out").resolve(), target_universe=targets)


def test_fixture_subset_is_deterministic_and_retains_coverage(tmp_path: Path) -> None:
    snapshot = ingest_local_release(request(tmp_path))
    assert snapshot.terminal_status == "valid"
    assert (tmp_path / "out" / "gene_effect_subset.tsv").is_file()
    assert "TP53" not in (tmp_path / "out" / "gene_effect_subset.tsv").read_text()
    coverage = json.loads((tmp_path / "out" / "coverage_summary.json").read_text())
    assert coverage["resolved_target_count"] == 2
    assert coverage["unresolved_target_count"] == 1
    assert "biological evidence quality" in coverage["limitation"]
    assert snapshot.snapshot_id == ingest_local_release(request(tmp_path / "second")).snapshot_id


def test_matrix_specific_coverage_excludes_probability_only_gene_effect_target(tmp_path: Path) -> None:
    snapshot = ingest_local_release(request(
        tmp_path,
        targets=[DepMapTargetRequest("CDK4", "symbol")],
    ))
    assert snapshot.target_resolution_coverage[0]["resolution_status"] == "resolved_exact_symbol"
    coverage = json.loads((tmp_path / "out" / "coverage_summary.json").read_text())
    assert coverage["resolved_target_count"] == 1
    assert coverage["gene_effect_coverage"] == 0
    assert coverage["dependency_probability_coverage"] == 1


def test_request_identity_is_scientific_not_operational(tmp_path: Path) -> None:
    first = request(tmp_path)
    reordered = request(tmp_path / "another", targets=list(reversed(first.target_universe or ())))
    assert first.target_universe_id == reordered.target_universe_id
    assert first.request_id == reordered.request_id
    assert first.request_id != request(tmp_path, "full_matrix", None).request_id
    changed_mapping = DepMapIngestionRequest(
        INGESTION_REQUEST_FORMAT_VERSION, manifest(), "target_subset", FIXTURE.resolve(),
        (tmp_path / "mapping").resolve(), mapping_version="depmap-modelid-v2",
        target_universe=first.target_universe,
    )
    release_payload = json.loads((FIXTURE / "release_manifest.json").read_text())
    release_payload["release_identifier"] = "synthetic-fixture-502b"
    changed_release = DepMapIngestionRequest(
        INGESTION_REQUEST_FORMAT_VERSION, DepMapReleaseManifest.from_dict(release_payload), "target_subset",
        FIXTURE.resolve(), (tmp_path / "release").resolve(), target_universe=first.target_universe,
    )
    assert first.request_id != changed_mapping.request_id
    assert first.request_id != changed_release.request_id
    with pytest.raises(ValueError, match="requires a target universe"):
        request(tmp_path, "target_subset", [])


def test_full_matrix_indexes_all_columns_without_matrix_copy(tmp_path: Path) -> None:
    snapshot = ingest_local_release(request(tmp_path, "full_matrix", None))
    assert snapshot.ingestion_mode == "full_matrix"
    assert not (tmp_path / "out" / "gene_effect_subset.tsv").exists()
    assert len((tmp_path / "out" / "gene_index.tsv").read_text().splitlines()) == 11


def test_mixed_case_gene_labels_are_parsed_and_resolved_exactly(tmp_path: Path) -> None:
    parsed = parse_gene_label("C9orf72 (79087)")
    assert (parsed.parsed_symbol, parsed.parsed_entrez_identifier, parsed.parser_status) == (
        "C9orf72", "79087", "parsed",
    )
    source = copied_fixture(tmp_path)
    effect = (source / "gene_effect.csv").read_text(encoding="utf-8").replace(
        "TP53 (7157)", "C9orf72 (79087)", 1,
    )
    release = manifest_for(source, {"gene_effect.csv": effect})
    snapshot = ingest_local_release(source_request(
        tmp_path,
        source,
        mode="target_subset",
        targets=[DepMapTargetRequest("C9orf72", "symbol"), DepMapTargetRequest("79087", "entrez")],
        release=release,
    ))
    assert [item["resolution_status"] for item in snapshot.target_resolution_coverage] == [
        "resolved_exact_entrez", "resolved_exact_symbol",
    ]
    gene_index = (tmp_path / "out" / "gene_index.tsv").read_text(encoding="utf-8")
    assert "C9orf72 (79087)\tC9orf72\t79087\tparsed" in gene_index


def test_example_ingestion_entry_point_succeeds_on_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = (tmp_path / "example-output").resolve()
    monkeypatch.setattr("sys.argv", [
        "run_local_ingestion.py",
        "--manifest", str((FIXTURE / "release_manifest.json").resolve()),
        "--data-root", str(FIXTURE.resolve()),
        "--mode", "target_subset",
        "--targets", str((FIXTURE / "target_subset.tsv").resolve()),
        "--output-dir", str(output),
    ])
    assert run_local_ingestion() == 0
    for filename in (
        "ingestion_snapshot.json", "coverage_summary.json", "gene_index.tsv",
        "model_index.tsv", "gene_effect_subset.tsv", "dependency_probability_subset.tsv",
    ):
        assert (output / filename).is_file()


def test_invalid_integrity_fails_before_artifacts(tmp_path: Path) -> None:
    altered = tmp_path / "source"; altered.mkdir()
    for source in FIXTURE.iterdir():
        if source.name != "gene_effect.csv": (altered / source.name).write_bytes(source.read_bytes())
    (altered / "gene_effect.csv").write_text("bad")
    broken = DepMapIngestionRequest(INGESTION_REQUEST_FORMAT_VERSION, manifest(), "full_matrix", altered.resolve(), (tmp_path / "out").resolve())
    with pytest.raises(DepMapIngestionError, match="local file size"):
        ingest_local_release(broken)
    assert not (tmp_path / "out" / "ingestion_snapshot.json").exists()


def test_checksum_missing_and_schema_fail_closed_before_artifacts(tmp_path: Path) -> None:
    missing = copied_fixture(tmp_path / "missing")
    (missing / "gene_effect.csv").unlink()
    with pytest.raises(DepMapIngestionError, match="file is absent"):
        ingest_local_release(source_request(tmp_path / "missing", missing, release=manifest()))

    checksum = copied_fixture(tmp_path / "checksum")
    path = checksum / "gene_effect.csv"
    path.write_text(path.read_text().replace("-0.5", "-0.9", 1), encoding="utf-8")
    with pytest.raises(DepMapIngestionError, match="checksum"):
        ingest_local_release(source_request(tmp_path / "checksum", checksum, release=manifest()))

    schema = copied_fixture(tmp_path / "schema")
    release = manifest_for(schema, {"gene_effect.csv": "Other,BRAF (673)\nACH-001,-0.5\n"})
    with pytest.raises(DepMapIngestionError, match="header"):
        ingest_local_release(source_request(tmp_path / "schema", schema, release=release))
    assert not (tmp_path / "schema" / "out" / "ingestion_snapshot.json").exists()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("ModelID,BRAF (673)\nACH-001,-0.5\nACH-001,-0.6\n", "duplicate ModelID"),
        ("ModelID,BRAF (673)\n,-0.5\n", "empty ModelID"),
        ("ModelID,BRAF (673)\nACH-001,not-a-number\n", "invalid numeric"),
        ("ModelID,BRAF (673),NRAS (4893)\nACH-001,-0.5\n", "row width"),
    ],
)
def test_matrix_parse_failures_are_explicit(tmp_path: Path, content: str, message: str) -> None:
    source = copied_fixture(tmp_path)
    release = manifest_for(source, {"gene_effect.csv": content})
    with pytest.raises(DepMapIngestionError, match=message):
        ingest_local_release(source_request(tmp_path, source, release=release))


def test_subset_resolution_retains_invalid_duplicate_unresolved_and_ambiguous_requests(tmp_path: Path) -> None:
    source = copied_fixture(tmp_path)
    content = (source / "gene_effect.csv").read_text().replace(
        "TP53 (7157)", "BRAF (999)", 1
    )
    release = manifest_for(source, {"gene_effect.csv": content})
    targets = [
        DepMapTargetRequest("BRAF", "symbol"),
        DepMapTargetRequest("BRAF", "symbol"),
        DepMapTargetRequest("", "symbol"),
        DepMapTargetRequest("NOT_A_GENE", "symbol"),
    ]
    snapshot = ingest_local_release(source_request(tmp_path, source, mode="target_subset", targets=targets, release=release))
    statuses = [item["resolution_status"] for item in snapshot.target_resolution_coverage]
    assert statuses == ["invalid_request", "ambiguous", "duplicate_request", "unresolved"]
    subset = (tmp_path / "out" / "gene_effect_subset.tsv").read_text()
    assert subset == "ModelID\nACH-001\nACH-002\nACH-003\nACH-004\n"


def test_reconciliation_missing_values_and_artifact_bytes_are_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_snapshot = ingest_local_release(request(first))
    second_snapshot = ingest_local_release(request(second))
    assert first_snapshot.snapshot_id == second_snapshot.snapshot_id
    assert first_snapshot.reconciliation_summary == {
        "models_shared": 3, "models_only_gene_effect": 1,
        "models_only_dependency_probability": 1, "models_missing_metadata": 1,
        "metadata_models_absent_from_matrices": 0, "genes_shared": 4,
        "genes_only_gene_effect": 1, "genes_only_dependency_probability": 1,
        "malformed_or_ambiguous_gene_columns": 2,
    }
    for filename in ("ingestion_snapshot.json", "coverage_summary.json", "gene_index.tsv", "model_index.tsv", "gene_effect_subset.tsv", "dependency_probability_subset.tsv"):
        assert (first / "out" / filename).read_bytes() == (second / "out" / filename).read_bytes()
    effect_subset = (first / "out" / "gene_effect_subset.tsv").read_text()
    assert "ACH-001\t-0.5\t" in effect_subset
    missing_request = request(first / "missing-values", targets=[DepMapTargetRequest("BRAF", "symbol"), DepMapTargetRequest("PTEN", "symbol")])
    ingest_local_release(missing_request)
    assert "ACH-001\t-0.5\t\n" in (first / "missing-values" / "out" / "gene_effect_subset.tsv").read_text()
    coverage = json.loads((first / "out" / "coverage_summary.json").read_text())
    assert coverage["optional_dataset_role_availability"] == {
        "common_essential_reference": True,
        "crispr_dependency_probability": True,
        "pan_dependency_reference": False,
    }
    gene_index = (first / "out" / "gene_index.tsv").read_text()
    assert "BAD LABEL\t\t\tmalformed" in gene_index


def test_source_escape_is_rejected(tmp_path: Path) -> None:
    source = copied_fixture(tmp_path)
    outside = tmp_path / "outside.csv"
    outside.write_bytes((source / "gene_effect.csv").read_bytes())
    (source / "gene_effect.csv").unlink()
    (source / "gene_effect.csv").symlink_to(outside)
    with pytest.raises(DepMapIngestionError, match="escapes source root"):
        ingest_local_release(source_request(tmp_path, source, release=manifest()))
