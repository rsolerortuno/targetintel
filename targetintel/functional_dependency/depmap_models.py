"""Immutable, deterministic release contracts for future local DepMap ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse


FILE_MANIFEST_FORMAT_VERSION = "v0.5.0"
SCHEMA_FINGERPRINT_FORMAT_VERSION = "v0.5.0"
RELEASE_MANIFEST_SCHEMA_ID = "targetintel.depmap-release-manifest"
RELEASE_MANIFEST_SCHEMA_VERSION = "v0.5.0"
LOCAL_LAYOUT_REQUEST_FORMAT_VERSION = "v0.5.0"

DATASET_ROLES = frozenset({
    "crispr_gene_effect", "crispr_dependency_probability", "model_metadata",
    "common_essential_reference", "pan_dependency_reference", "release_readme",
})
FILE_FORMATS = frozenset({"csv", "tsv", "text"})
RELEASE_DECLARATION_STATES = frozenset({"declared", "validated"})
CACHE_POLICIES = frozenset({"read_only", "reuse_if_valid", "refresh_forbidden"})
INGESTION_MODES = frozenset({"full_matrix", "target_subset"})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(_thaw(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _identity(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}_{sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _relative_filename(value: str) -> bool:
    if not _text(value) or "\\" in value or urlparse(value).scheme:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and path.name not in {"", "."}


def _safe_release_directory(value: str) -> bool:
    return _relative_filename(value) and len(PurePosixPath(value).parts) == 1


def _forbidden_nested(value: Any) -> bool:
    forbidden = ("credential", "password", "secret", "token", "authorization", "reasoning", "thinking", "chain_of_thought")
    if isinstance(value, Mapping):
        return any(
            _forbidden_nested(str(key)) or _forbidden_nested(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list)):
        return any(_forbidden_nested(item) for item in value)
    return isinstance(value, str) and any(marker in value.casefold() for marker in forbidden)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _strict_values(data: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    unknown = set(data) - allowed
    missing = allowed - set(data)
    _require(not unknown and not missing, "unknown or missing manifest fields")
    return dict(data)


@dataclass(frozen=True)
class DepMapSchemaFingerprint:
    schema_fingerprint_format_version: str
    dataset_role: str
    identifier_orientation: str
    required_identifier_fields: tuple[str, ...] | list[str]
    canonical_required_columns: tuple[str, ...] | list[str]
    gene_column_naming_contract: str | None
    model_identifier_contract: str | None
    primitive_value_type: str
    nullable_field_policy: str
    schema_mapping_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_identifier_fields", tuple(self.required_identifier_fields))
        object.__setattr__(self, "canonical_required_columns", tuple(self.canonical_required_columns))
        _require(self.schema_fingerprint_format_version == SCHEMA_FINGERPRINT_FORMAT_VERSION, "unsupported schema-fingerprint format version")
        _require(self.dataset_role in DATASET_ROLES, "unknown dataset role")
        _require(all(_text(item) for item in self.required_identifier_fields + self.canonical_required_columns), "schema identifier fields must be non-empty")
        _require(len(set(self.required_identifier_fields)) == len(self.required_identifier_fields), "duplicate required identifier field")
        _require(len(set(self.canonical_required_columns)) == len(self.canonical_required_columns), "duplicate canonical required column")
        _require(all(_text(getattr(self, field)) for field in ("identifier_orientation", "primitive_value_type", "nullable_field_policy", "schema_mapping_version")), "schema fields must be non-empty")
        matrix_roles = {"crispr_gene_effect", "crispr_dependency_probability"}
        if self.dataset_role in matrix_roles:
            _require(self.identifier_orientation == "models_by_genes", "CRISPR matrices must be models_by_genes")
            _require(self.required_identifier_fields == ("ModelID",), "CRISPR matrices must require ModelID")
            _require(self.canonical_required_columns == ("ModelID",), "CRISPR matrices must canonically require ModelID")
            _require(self.gene_column_naming_contract == "depmap_symbol_entrez_label", "CRISPR matrices require the approved gene-label contract")
            _require(self.model_identifier_contract == "ModelID", "CRISPR matrices require ModelID contract")
            _require(self.primitive_value_type == "float", "CRISPR matrices require float values")
        elif self.dataset_role == "model_metadata":
            _require(self.identifier_orientation == "model_metadata_rows", "model metadata must be row-oriented")
            _require(self.required_identifier_fields == ("ModelID",), "model metadata must require ModelID")
            _require("ModelID" in self.canonical_required_columns, "model metadata must include ModelID")
            _require(self.gene_column_naming_contract is None and self.model_identifier_contract == "ModelID", "model metadata identifier contracts are fixed")
        elif self.dataset_role in {"common_essential_reference", "pan_dependency_reference"}:
            _require(self.identifier_orientation == "gene_reference_rows", "gene references must be gene-oriented")
            _require(self.required_identifier_fields == ("gene_label",), "gene references must require gene_label")
            _require(self.gene_column_naming_contract == "depmap_symbol_entrez_label", "gene references require approved gene labels")
            _require(self.model_identifier_contract is None, "gene references must not declare model identifiers")
        else:
            _require(self.identifier_orientation == "release_document", "release README must be a release document")
            _require(not self.required_identifier_fields and not self.canonical_required_columns, "release README must not declare tabular fields")
            _require(self.gene_column_naming_contract is None and self.model_identifier_contract is None, "release README must not declare identifier contracts")

    @property
    def schema_fingerprint_id(self) -> str:
        return _identity("dmsf", self.identity_payload())

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_fingerprint_format_version": self.schema_fingerprint_format_version,
            "dataset_role": self.dataset_role,
            "identifier_orientation": self.identifier_orientation,
            "required_identifier_fields": list(self.required_identifier_fields),
            "canonical_required_columns": list(self.canonical_required_columns),
            "gene_column_naming_contract": self.gene_column_naming_contract,
            "model_identifier_contract": self.model_identifier_contract,
            "primitive_value_type": self.primitive_value_type,
            "nullable_field_policy": self.nullable_field_policy,
            "schema_mapping_version": self.schema_mapping_version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "schema_fingerprint_id": self.schema_fingerprint_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DepMapSchemaFingerprint":
        values = dict(data)
        supplied_id = values.pop("schema_fingerprint_id", None)
        schema = cls(**_strict_values(values, set(cls.__dataclass_fields__)))
        _require(supplied_id is None or supplied_id == schema.schema_fingerprint_id, "schema_fingerprint_id does not match content")
        return schema


@dataclass(frozen=True)
class DepMapFileManifest:
    file_manifest_format_version: str
    dataset_role: str
    relative_filename: str
    file_format: str
    required: bool
    sha256_checksum: str
    expected_size_bytes: int
    schema_fingerprint: DepMapSchemaFingerprint
    source_description: str | None = None
    limitations: tuple[str, ...] | list[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "limitations", tuple(self.limitations))
        _require(self.file_manifest_format_version == FILE_MANIFEST_FORMAT_VERSION, "unsupported file-manifest format version")
        _require(self.dataset_role in DATASET_ROLES, "unknown dataset role")
        _require(_relative_filename(self.relative_filename), "relative_filename must be a safe relative local filename")
        _require(self.file_format in FILE_FORMATS, "unknown file format")
        _require(isinstance(self.required, bool), "required must be boolean")
        _require(isinstance(self.sha256_checksum, str) and len(self.sha256_checksum) == 64 and all(char in "0123456789abcdef" for char in self.sha256_checksum), "sha256_checksum must be a lowercase SHA-256 hex digest")
        _require(isinstance(self.expected_size_bytes, int) and not isinstance(self.expected_size_bytes, bool) and self.expected_size_bytes >= 0, "expected_size_bytes must be non-negative")
        _require(isinstance(self.schema_fingerprint, DepMapSchemaFingerprint) and self.schema_fingerprint.dataset_role == self.dataset_role, "schema fingerprint must match dataset role")
        _require(self.source_description is None or _text(self.source_description), "source_description must be non-empty or null")
        _require(all(_text(item) for item in self.limitations), "limitations must contain non-empty strings")

    @property
    def file_manifest_id(self) -> str:
        return _identity("dmfm", self.identity_payload())

    def identity_payload(self) -> dict[str, Any]:
        return {
            "file_manifest_format_version": self.file_manifest_format_version, "dataset_role": self.dataset_role,
            "relative_filename": self.relative_filename, "file_format": self.file_format, "required": self.required,
            "sha256_checksum": self.sha256_checksum, "expected_size_bytes": self.expected_size_bytes,
            "schema_fingerprint_id": self.schema_fingerprint.schema_fingerprint_id,
            "source_description": self.source_description, "limitations": list(self.limitations),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "file_manifest_id": self.file_manifest_id, "schema_fingerprint": self.schema_fingerprint.to_dict()}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DepMapFileManifest":
        values = dict(data)
        supplied_id = values.pop("file_manifest_id", None)
        values.pop("schema_fingerprint_id", None)
        fingerprint = values.pop("schema_fingerprint", None)
        _require(isinstance(fingerprint, Mapping), "schema_fingerprint must be a mapping")
        values["schema_fingerprint"] = DepMapSchemaFingerprint.from_dict(fingerprint)
        file_manifest = cls(**_strict_values(values, set(cls.__dataclass_fields__)))
        _require(supplied_id is None or supplied_id == file_manifest.file_manifest_id, "file_manifest_id does not match content")
        return file_manifest


@dataclass(frozen=True)
class DepMapReleaseManifest:
    manifest_schema_id: str
    manifest_schema_version: str
    source_name: str
    release_identifier: str
    declaration_state: str
    file_manifests: tuple[DepMapFileManifest, ...] | list[DepMapFileManifest]
    required_dataset_roles: tuple[str, ...] | list[str]
    optional_dataset_roles: tuple[str, ...] | list[str]
    release_limitations: tuple[str, ...] | list[str]
    research_use_boundary: str
    operational_metadata: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        files = tuple(sorted(self.file_manifests, key=lambda item: item.dataset_role))
        required = tuple(sorted(self.required_dataset_roles))
        optional = tuple(sorted(self.optional_dataset_roles))
        object.__setattr__(self, "file_manifests", files)
        object.__setattr__(self, "required_dataset_roles", required)
        object.__setattr__(self, "optional_dataset_roles", optional)
        object.__setattr__(self, "release_limitations", tuple(self.release_limitations))
        object.__setattr__(self, "operational_metadata", _freeze(self.operational_metadata or {}))
        _require(self.manifest_schema_id == RELEASE_MANIFEST_SCHEMA_ID, "unsupported release-manifest schema ID")
        _require(self.manifest_schema_version == RELEASE_MANIFEST_SCHEMA_VERSION, "unsupported release-manifest schema version")
        _require(_text(self.source_name) and _text(self.release_identifier) and _text(self.research_use_boundary), "release identity fields must be non-empty")
        _require(self.declaration_state in RELEASE_DECLARATION_STATES, "unknown release declaration state")
        _require(all(isinstance(item, DepMapFileManifest) for item in files), "file_manifests must contain file manifests")
        _require(set(required).isdisjoint(optional), "required and optional roles must not overlap")
        _require(set(required).issubset(DATASET_ROLES) and set(optional).issubset(DATASET_ROLES), "unknown declared dataset role")
        _require(len(required) == len(set(required)) and len(optional) == len(set(optional)), "duplicate declared dataset role")
        _require({"crispr_gene_effect", "model_metadata", "release_readme"}.issubset(required), "missing required core dataset role")
        roles = [item.dataset_role for item in files]
        names = [item.relative_filename for item in files]
        ids = [item.file_manifest_id for item in files]
        _require(len(roles) == len(set(roles)), "duplicate file dataset role")
        _require(len(names) == len(set(names)), "duplicate relative filename")
        _require(len(ids) == len(set(ids)), "duplicate file manifest identity")
        _require(set(roles).issubset(set(required) | set(optional)), "file manifest has undeclared role")
        _require(set(required).issubset(set(roles)), "missing required dataset role")
        _require(all(item.required == (item.dataset_role in required) for item in files), "file required state must match declared role")
        _require(all(_text(item) for item in self.release_limitations), "release limitations must contain non-empty strings")
        _require(not _forbidden_nested(self.operational_metadata), "operational metadata contains credentials or hidden reasoning")

    @property
    def manifest_id(self) -> str:
        return _identity("dmrm", self.identity_payload())

    @property
    def unavailable_optional_roles(self) -> tuple[str, ...]:
        present = {item.dataset_role for item in self.file_manifests}
        return tuple(role for role in self.optional_dataset_roles if role not in present)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "manifest_schema_id": self.manifest_schema_id, "manifest_schema_version": self.manifest_schema_version,
            "source_name": self.source_name, "release_identifier": self.release_identifier,
            "declaration_state": self.declaration_state,
            "file_manifests": [item.identity_payload() for item in self.file_manifests],
            "required_dataset_roles": list(self.required_dataset_roles), "optional_dataset_roles": list(self.optional_dataset_roles),
            "schema_fingerprint_ids": [item.schema_fingerprint.schema_fingerprint_id for item in self.file_manifests],
            "release_limitations": list(self.release_limitations), "research_use_boundary": self.research_use_boundary,
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.identity_payload()
        result["manifest_id"] = self.manifest_id
        result["file_manifests"] = [item.to_dict() for item in self.file_manifests]
        result["unavailable_optional_roles"] = list(self.unavailable_optional_roles)
        result["operational_metadata"] = _thaw(self.operational_metadata)
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DepMapReleaseManifest":
        values = dict(data)
        supplied_id = values.pop("manifest_id", None)
        values.setdefault("operational_metadata", None)
        values.pop("schema_fingerprint_ids", None)
        values.pop("unavailable_optional_roles", None)
        raw_files = values.get("file_manifests")
        _require(isinstance(raw_files, list), "file_manifests must be a list")
        values["file_manifests"] = [DepMapFileManifest.from_dict(item) for item in raw_files if isinstance(item, Mapping)]
        _require(len(values["file_manifests"]) == len(raw_files), "file_manifests must contain mappings")
        manifest = cls(**_strict_values(values, set(cls.__dataclass_fields__)))
        _require(supplied_id is None or supplied_id == manifest.manifest_id, "manifest_id does not match content")
        return manifest


@dataclass(frozen=True)
class DepMapLocalLayoutRequest:
    local_layout_request_format_version: str
    external_data_root: Path | str
    release_directory: str
    derived_data_root: Path | str
    cache_policy: str
    requesting_actor: str
    operational_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "external_data_root", Path(self.external_data_root))
        object.__setattr__(self, "derived_data_root", Path(self.derived_data_root))
        _require(self.local_layout_request_format_version == LOCAL_LAYOUT_REQUEST_FORMAT_VERSION, "unsupported local-layout request format version")
        _require(self.external_data_root.is_absolute() and self.derived_data_root.is_absolute(), "external and derived data roots must be explicit absolute paths")
        _require(_safe_release_directory(self.release_directory), "release_directory must be a safe single relative path component")
        _require(self.cache_policy in CACHE_POLICIES and _text(self.requesting_actor), "invalid cache policy or requesting actor")
        _require(self.operational_timestamp is None or (self.operational_timestamp.tzinfo is not None and self.operational_timestamp.utcoffset().total_seconds() == 0), "operational_timestamp must be UTC or null")

    @property
    def local_release_root(self) -> Path:
        return self.external_data_root / "depmap" / self.release_directory

    @property
    def local_derived_root(self) -> Path:
        return self.derived_data_root / "depmap" / self.release_directory

    @property
    def layout_request_id(self) -> str:
        return _identity("dmlr", self.identity_payload())

    def identity_payload(self) -> dict[str, Any]:
        return {"local_layout_request_format_version": self.local_layout_request_format_version, "release_directory": self.release_directory, "cache_policy": self.cache_policy, "requesting_actor": self.requesting_actor}
