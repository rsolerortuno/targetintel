"""Offline contract and isolation tests for Issue 501."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path

import pytest

from targetintel.functional_dependency import (
    DepMapFileManifest, DepMapLocalLayoutRequest, DepMapReleaseManifest,
    DepMapSchemaFingerprint, validate_local_release,
)
from targetintel.functional_dependency.depmap_models import (
    FILE_MANIFEST_FORMAT_VERSION, LOCAL_LAYOUT_REQUEST_FORMAT_VERSION,
    RELEASE_MANIFEST_SCHEMA_ID, RELEASE_MANIFEST_SCHEMA_VERSION,
    SCHEMA_FINGERPRINT_FORMAT_VERSION,
)


def schema(role: str = "crispr_gene_effect", **changes: object) -> DepMapSchemaFingerprint:
    values: dict[str, object] = {
        "schema_fingerprint_format_version": SCHEMA_FINGERPRINT_FORMAT_VERSION, "dataset_role": role,
        "identifier_orientation": "models_by_genes", "required_identifier_fields": ["ModelID"],
        "canonical_required_columns": ["ModelID"], "gene_column_naming_contract": "depmap_symbol_entrez_label",
        "model_identifier_contract": "ModelID", "primitive_value_type": "float",
        "nullable_field_policy": "values_may_be_missing", "schema_mapping_version": "depmap-header-v1",
    }
    if role == "model_metadata":
        values.update(identifier_orientation="model_metadata_rows", canonical_required_columns=["ModelID", "OncotreeLineage", "PrimaryDisease"], gene_column_naming_contract=None, primitive_value_type="string")
    elif role in {"common_essential_reference", "pan_dependency_reference"}:
        values.update(identifier_orientation="gene_reference_rows", required_identifier_fields=["gene_label"], canonical_required_columns=["gene_label"], gene_column_naming_contract="depmap_symbol_entrez_label", model_identifier_contract=None, primitive_value_type="string")
    elif role == "release_readme":
        values.update(identifier_orientation="release_document", required_identifier_fields=[], canonical_required_columns=[], gene_column_naming_contract=None, model_identifier_contract=None, primitive_value_type="string")
    values.update(changes)
    return DepMapSchemaFingerprint(**values)  # type: ignore[arg-type]


def file(role: str, name: str, content: bytes, required: bool = True, **changes: object) -> DepMapFileManifest:
    values: dict[str, object] = {
        "file_manifest_format_version": FILE_MANIFEST_FORMAT_VERSION, "dataset_role": role,
        "relative_filename": name, "file_format": "text" if role == "release_readme" else "csv",
        "required": required, "sha256_checksum": sha256(content).hexdigest(), "expected_size_bytes": len(content),
        "schema_fingerprint": schema(role), "source_description": "local CI fixture", "limitations": ["Fixture only"],
    }
    values.update(changes)
    return DepMapFileManifest(**values)  # type: ignore[arg-type]


def manifest(files: list[DepMapFileManifest] | None = None, **changes: object) -> DepMapReleaseManifest:
    if files is None:
        files = [
            file("crispr_gene_effect", "gene_effect.csv", b"ModelID,BRAF (673)\nACH-1,-0.5\n"),
            file("model_metadata", "models.csv", b"ModelID,OncotreeLineage,PrimaryDisease\nACH-1,Skin,Melanoma\n"),
            file("release_readme", "README.txt", b"Fixture release\n"),
        ]
    values: dict[str, object] = {
        "manifest_schema_id": RELEASE_MANIFEST_SCHEMA_ID, "manifest_schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "source_name": "DepMap Public", "release_identifier": "fixture-1", "declaration_state": "declared",
        "file_manifests": files, "required_dataset_roles": ["release_readme", "model_metadata", "crispr_gene_effect"],
        "optional_dataset_roles": ["crispr_dependency_probability", "common_essential_reference", "pan_dependency_reference"],
        "release_limitations": ["Offline fixture; not a real release"], "research_use_boundary": "Research context only; no clinical interpretation.",
    }
    values.update(changes)
    return DepMapReleaseManifest(**values)  # type: ignore[arg-type]


def layout(tmp_path: Path, **changes: object) -> DepMapLocalLayoutRequest:
    values: dict[str, object] = {
        "local_layout_request_format_version": LOCAL_LAYOUT_REQUEST_FORMAT_VERSION,
        "external_data_root": tmp_path / "external", "release_directory": "fixture-1",
        "derived_data_root": tmp_path / "derived", "cache_policy": "read_only", "requesting_actor": "issue-501",
    }
    values.update(changes)
    return DepMapLocalLayoutRequest(**values)  # type: ignore[arg-type]


def materialize(tmp_path: Path, items: list[DepMapFileManifest]) -> None:
    root = tmp_path / "external" / "depmap" / "fixture-1"
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        "gene_effect.csv": b"ModelID,BRAF (673)\nACH-1,-0.5\n",
        "models.csv": b"ModelID,OncotreeLineage,PrimaryDisease\nACH-1,Skin,Melanoma\n",
        "README.txt": b"Fixture release\n",
    }
    for item in items:
        (root / item.relative_filename).write_bytes(payloads[item.relative_filename])


def test_file_and_schema_contracts_are_immutable_deterministic_and_fail_closed() -> None:
    first = file("crispr_gene_effect", "gene_effect.csv", b"x")
    assert first.file_manifest_format_version == FILE_MANIFEST_FORMAT_VERSION
    assert first.file_manifest_id == file("crispr_gene_effect", "gene_effect.csv", b"x").file_manifest_id
    assert first.to_dict()["file_manifest_id"] == first.file_manifest_id
    assert DepMapFileManifest.from_dict(first.to_dict()).to_dict() == first.to_dict()
    with pytest.raises(FrozenInstanceError): first.relative_filename = "other.csv"  # type: ignore[misc]
    with pytest.raises(ValueError, match="SHA-256"): file("crispr_gene_effect", "x.csv", b"x", sha256_checksum="bad")
    with pytest.raises(ValueError, match="non-negative"): file("crispr_gene_effect", "x.csv", b"x", expected_size_bytes=-1)
    for name in ("/absolute.csv", "../traversal.csv", "https://example.test/file.csv"):
        with pytest.raises(ValueError): file("crispr_gene_effect", name, b"x")
    with pytest.raises(ValueError, match="unknown dataset role"): file("unknown", "x.csv", b"x")
    with pytest.raises(ValueError, match="unknown file format"): file("crispr_gene_effect", "x.csv", b"x", file_format="parquet")
    effect, probability, metadata = schema(), schema("crispr_dependency_probability"), schema("model_metadata")
    assert effect.schema_fingerprint_format_version == SCHEMA_FINGERPRINT_FORMAT_VERSION
    assert effect.schema_fingerprint_id != replace(effect, schema_mapping_version="depmap-header-v2").schema_fingerprint_id
    assert effect.schema_fingerprint_id != probability.schema_fingerprint_id != metadata.schema_fingerprint_id
    with pytest.raises(FrozenInstanceError): effect.schema_mapping_version = "x"  # type: ignore[misc]
    invalid = effect.to_dict() | {"unrecognized": "field"}
    with pytest.raises(ValueError, match="unknown or missing"): DepMapSchemaFingerprint.from_dict(invalid)


def test_release_manifest_is_canonical_deeply_immutable_and_identity_excludes_operations(tmp_path: Path) -> None:
    items = manifest().file_manifests
    first = manifest(list(reversed(items)), operational_metadata={"download_timestamp": "later"})
    second = manifest(list(items), operational_metadata={"download_timestamp": "earlier"})
    assert first.manifest_schema_id == RELEASE_MANIFEST_SCHEMA_ID
    assert first.manifest_schema_version == RELEASE_MANIFEST_SCHEMA_VERSION
    assert first.manifest_id == second.manifest_id
    assert first.to_dict()["manifest_id"] == first.manifest_id
    assert DepMapReleaseManifest.from_dict(first.to_dict()).to_dict() == first.to_dict()
    assert first.file_manifests == tuple(sorted(items, key=lambda item: item.dataset_role))
    assert first.unavailable_optional_roles == ("common_essential_reference", "crispr_dependency_probability", "pan_dependency_reference")
    with pytest.raises(TypeError): first.operational_metadata["x"] = "y"  # type: ignore[index]
    with pytest.raises(ValueError, match="duplicate file dataset role"): manifest(list(items) + [items[0]])
    with pytest.raises(ValueError, match="duplicate relative filename"): manifest([items[0], replace(items[1], relative_filename=items[0].relative_filename), items[2]])
    with pytest.raises(ValueError, match="missing required dataset role"): manifest(items[:2])
    assert first.manifest_id != replace(first, release_identifier="fixture-2").manifest_id
    assert first.manifest_id != manifest([replace(items[0], sha256_checksum="0" * 64), *items[1:]]).manifest_id
    assert first.manifest_id != manifest([replace(items[0], schema_fingerprint=replace(items[0].schema_fingerprint, schema_mapping_version="v2")), *items[1:]]).manifest_id
    assert layout(tmp_path).layout_request_id == replace(layout(tmp_path), external_data_root=tmp_path / "another").layout_request_id


@pytest.mark.parametrize(
    "operational_metadata",
    [
        {"note": "Authorization: Bearer secret-token-abc"},
        {"audit": [{"log": "chain_of_thought: internal deliberation"}]},
    ],
)
def test_release_manifest_rejects_credentials_and_hidden_reasoning_in_nested_values(
    operational_metadata: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="credentials or hidden reasoning"):
        manifest(operational_metadata=operational_metadata)


def test_layout_rejects_implicit_or_traversal_paths(tmp_path: Path) -> None:
    request = layout(tmp_path)
    with pytest.raises(FrozenInstanceError): request.cache_policy = "reuse_if_valid"  # type: ignore[misc]
    with pytest.raises(ValueError): layout(tmp_path, external_data_root="relative")
    with pytest.raises(ValueError): layout(tmp_path, derived_data_root="relative")
    with pytest.raises(ValueError): layout(tmp_path, release_directory="../other")


def test_small_fixture_validation_distinguishes_file_integrity_schema_and_release(tmp_path: Path) -> None:
    release = manifest()
    materialize(tmp_path, list(release.file_manifests))
    request = layout(tmp_path)
    assert validate_local_release(release, request).status == "valid"
    assert validate_local_release(release, request, expected_release_identifier="other").status == "release_mismatch"
    (request.local_release_root / "gene_effect.csv").unlink()
    assert validate_local_release(release, request).status == "missing_file"
    materialize(tmp_path, [release.file_manifests[0]])
    (request.local_release_root / "gene_effect.csv").write_bytes(b"wrong")
    assert validate_local_release(release, request).status == "size_mismatch"
    same_size_wrong_bytes = b"ModelID,BRAF (673)\nACH-1,-0.6\n"
    (request.local_release_root / "gene_effect.csv").write_bytes(same_size_wrong_bytes)
    assert validate_local_release(release, request).status == "checksum_mismatch"
    expected = release.file_manifests[0]
    wrong_header = b"NotModelID,BRAF (673)\nACH-1,-0.5\n"
    changed = replace(expected, expected_size_bytes=len(wrong_header), sha256_checksum=sha256(wrong_header).hexdigest())
    schema_release = manifest([changed, *[item for item in release.file_manifests if item.dataset_role != expected.dataset_role]])
    (request.local_release_root / "gene_effect.csv").write_bytes(wrong_header)
    assert validate_local_release(schema_release, request).status == "schema_mismatch"


def test_contract_modules_are_isolated_from_pipeline_and_operational_mechanisms() -> None:
    root = Path(__file__).parents[1] / "targetintel" / "functional_dependency"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    for forbidden in ("targetintel.scoring", "targetintel.intent_ranking", "targetintel.role_classifier", "targetintel.feature_table", "targetintel.modality", "targetintel.opentargets", "targetintel.llm", "hypothesis_cards", "html_reports", "subprocess", "requests", "urllib.request", "importlib", "eval("):
        assert forbidden not in source


def test_manifest_construction_and_validation_do_not_invoke_pipeline_layers(monkeypatch, tmp_path: Path) -> None:
    import targetintel.feature_table as feature_table
    import targetintel.html_reports as html_reports
    import targetintel.hypothesis_cards as hypothesis_cards
    import targetintel.intent_ranking as intent_ranking
    import targetintel.llm.execution as llm_execution
    import targetintel.modality as modality
    import targetintel.opentargets as opentargets
    import targetintel.role_classifier as role_classifier
    import targetintel.scoring as scoring

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("a prohibited pipeline layer was invoked")

    for module, function in (
        (scoring, "score_all_profiles"), (intent_ranking, "add_intent_ranks"),
        (role_classifier, "classify_gene"), (feature_table, "build_feature_table"),
        (modality, "assign_modality_fit"), (opentargets, "get_melanoma_associated_targets"),
        (llm_execution, "execute_request"), (hypothesis_cards, "make_target_card"),
        (html_reports, "make_target_html_report"),
    ):
        monkeypatch.setattr(module, function, forbidden)
    release = manifest()
    assert validate_local_release(release, layout(tmp_path)).status == "missing_file"
