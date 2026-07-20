"""Deterministic, local-only ingestion of release-pinned DepMap files.

This module deliberately normalizes identities and artifacts only.  It does
not calculate dependency profiles, lineage selectivity, scores, or rankings.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from .depmap_models import (
    DATASET_ROLES, INGESTION_MODES, DepMapLocalLayoutRequest,
    DepMapReleaseManifest, canonical_json, _forbidden_nested, _identity,
    _text, _freeze, _thaw,
)
from .depmap_validation import validate_local_release


INGESTION_REQUEST_FORMAT_VERSION = "v0.5.0"
INGESTION_SNAPSHOT_FORMAT_VERSION = "v0.5.0"
GENE_LABEL_PARSER_VERSION = "depmap-gene-label-v2"
MODEL_MAPPING_VERSION = "depmap-modelid-v1"
MATRIX_ROLES = ("crispr_gene_effect", "crispr_dependency_probability")


class DepMapIngestionError(ValueError):
    """Sanitized, terminal ingestion error; never includes a traceback."""

    def __init__(self, status: str, message: str) -> None:
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class DepMapTargetRequest:
    requested_identifier: str
    requested_identifier_type: str

    def __post_init__(self) -> None:
        # Target-universe files are untrusted operational input.  Keep malformed
        # entries so resolution coverage can report ``invalid_request`` rather
        # than losing the request to an exception before ingestion begins.
        pass

    @property
    def normalized_request(self) -> str:
        # Exact identifiers are intentionally not case-folded or alias-mapped.
        return self.requested_identifier.strip() if isinstance(self.requested_identifier, str) else ""

    @property
    def is_valid(self) -> bool:
        return (
            self.requested_identifier_type in {"symbol", "entrez"}
            and bool(self.normalized_request)
        )

    def identity_payload(self) -> dict[str, str]:
        return {
            "requested_identifier": self.normalized_request,
            "requested_identifier_type": (
                self.requested_identifier_type
                if isinstance(self.requested_identifier_type, str)
                else ""
            ),
        }


@dataclass(frozen=True)
class DepMapIngestionRequest:
    request_format_version: str
    release_manifest: DepMapReleaseManifest
    ingestion_mode: str
    data_root: Path | str
    output_directory: Path | str
    parser_version: str = GENE_LABEL_PARSER_VERSION
    mapping_version: str = MODEL_MAPPING_VERSION
    requested_dataset_roles: tuple[str, ...] | list[str] = MATRIX_ROLES
    target_universe: tuple[DepMapTargetRequest, ...] | list[DepMapTargetRequest] | None = None
    operational_actor: str | None = None
    limitations: tuple[str, ...] | list[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_root", Path(self.data_root))
        object.__setattr__(self, "output_directory", Path(self.output_directory))
        roles = tuple(self.requested_dataset_roles)
        object.__setattr__(self, "requested_dataset_roles", tuple(sorted(roles)))
        object.__setattr__(self, "limitations", tuple(self.limitations))
        targets = None if self.target_universe is None else tuple(self.target_universe)
        object.__setattr__(self, "target_universe", targets)
        if self.request_format_version != INGESTION_REQUEST_FORMAT_VERSION:
            raise ValueError("unsupported ingestion request format version")
        if self.ingestion_mode not in INGESTION_MODES:
            raise ValueError("unknown ingestion mode")
        if not self.data_root.is_absolute() or not self.output_directory.is_absolute():
            raise ValueError("data_root and output_directory must be explicit absolute paths")
        if not set(self.requested_dataset_roles).issubset(DATASET_ROLES):
            raise ValueError("unknown requested dataset role")
        if len(roles) != len(set(roles)):
            raise ValueError("duplicate requested dataset role")
        if not set(MATRIX_ROLES).issubset(self.requested_dataset_roles):
            raise ValueError("both matrix roles must be explicitly requested")
        if self.ingestion_mode == "target_subset" and not targets:
            raise ValueError("target_subset mode requires a target universe")
        if self.ingestion_mode == "full_matrix" and targets is not None:
            raise ValueError("full_matrix mode rejects a target universe")
        if targets is not None and not all(isinstance(item, DepMapTargetRequest) for item in targets):
            raise ValueError("target_universe must contain target entries")
        if not _text(self.parser_version) or not _text(self.mapping_version):
            raise ValueError("parser and mapping versions must be non-empty")
        if self.operational_actor is not None and not _text(self.operational_actor):
            raise ValueError("operational actor must be non-empty or null")
        if _forbidden_nested({"parser_version": self.parser_version, "mapping_version": self.mapping_version, "operational_actor": self.operational_actor, "limitations": self.limitations}):
            raise ValueError("request contains credentials or hidden reasoning")
        if not all(_text(item) for item in self.limitations):
            raise ValueError("limitations must be safe non-empty strings")

    @property
    def target_universe_payload(self) -> list[dict[str, str]] | None:
        if self.target_universe is None:
            return None
        return sorted((item.identity_payload() for item in self.target_universe), key=canonical_json)

    @property
    def target_universe_id(self) -> str | None:
        if self.target_universe_payload is None:
            return None
        return _identity("dmtu", {"targets": self.target_universe_payload})

    def identity_payload(self) -> dict[str, Any]:
        return {"request_format_version": self.request_format_version, "release_manifest_id": self.release_manifest.manifest_id,
                "ingestion_mode": self.ingestion_mode, "parser_version": self.parser_version,
                "mapping_version": self.mapping_version, "requested_dataset_roles": list(self.requested_dataset_roles),
                "target_universe_id": self.target_universe_id, "limitations": list(self.limitations)}

    @property
    def request_id(self) -> str:
        return _identity("dmir", self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "request_id": self.request_id,
                "data_root": str(self.data_root), "output_directory": str(self.output_directory),
                "operational_actor": self.operational_actor,
                "release_manifest": self.release_manifest.to_dict(),
                "target_universe": self.target_universe_payload}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DepMapIngestionRequest":
        allowed = {"request_format_version", "release_manifest", "ingestion_mode", "data_root", "output_directory", "parser_version", "mapping_version", "requested_dataset_roles", "target_universe", "operational_actor", "limitations", "request_id", "release_manifest_id", "target_universe_id"}
        if set(data) - allowed:
            raise ValueError("unknown ingestion request fields")
        manifest_data = data.get("release_manifest")
        if not isinstance(manifest_data, Mapping):
            raise ValueError("release_manifest must be a mapping")
        raw_targets = data.get("target_universe")
        if raw_targets is not None and not isinstance(raw_targets, list):
            raise ValueError("target_universe must be a list or null")
        targets = None if raw_targets is None else [DepMapTargetRequest(item.get("requested_identifier", ""), item.get("requested_identifier_type", "")) for item in raw_targets if isinstance(item, Mapping)]
        if raw_targets is not None and len(targets) != len(raw_targets):
            raise ValueError("target_universe entries must be mappings")
        required = {"request_format_version", "ingestion_mode", "data_root", "output_directory"}
        if not required.issubset(data): raise ValueError("missing ingestion request fields")
        request = cls(data["request_format_version"], DepMapReleaseManifest.from_dict(manifest_data), data["ingestion_mode"], data["data_root"], data["output_directory"], data.get("parser_version", GENE_LABEL_PARSER_VERSION), data.get("mapping_version", MODEL_MAPPING_VERSION), data.get("requested_dataset_roles", MATRIX_ROLES), targets, data.get("operational_actor"), data.get("limitations", ()))
        if data.get("request_id") not in (None, request.request_id): raise ValueError("request_id does not match content")
        return request


@dataclass(frozen=True)
class GeneLabel:
    original_source_label: str
    parsed_symbol: str | None
    parsed_entrez_identifier: str | None
    parser_status: str
    parser_version: str = GENE_LABEL_PARSER_VERSION
    limitation: str = "Exact structured source labels only; no aliases or fuzzy matching."

    @property
    def canonical_identity(self) -> str | None:
        if self.parser_status != "parsed":
            return None
        return f"symbol:{self.parsed_symbol}|entrez:{self.parsed_entrez_identifier}" if self.parsed_entrez_identifier else f"symbol:{self.parsed_symbol}"


# HGNC-approved symbols are normally uppercase, but some approved symbols
# retain mixed-case components (for example, ``C9orf72``).  Matching preserves
# the source spelling exactly; this accepts no case-folding or repair.
_GENE_LABEL = re.compile(r"^([A-Za-z][A-Za-z0-9-]*) \(([1-9][0-9]*)\)$")
_SYMBOL_ONLY = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


def parse_gene_label(label: str, *, parser_version: str = GENE_LABEL_PARSER_VERSION) -> GeneLabel:
    """Parse only the approved, exact ``SYMBOL (ENTREZ)`` source contract."""
    if not isinstance(label, str) or not label:
        return GeneLabel(str(label), None, None, "malformed", parser_version)
    match = _GENE_LABEL.fullmatch(label)
    if match:
        return GeneLabel(label, match.group(1), match.group(2), "parsed", parser_version)
    if _SYMBOL_ONLY.fullmatch(label):
        return GeneLabel(label, label, None, "unresolved_format", parser_version)
    return GeneLabel(label, None, None, "malformed", parser_version)


def _delimiter(fmt: str) -> str:
    if fmt == "csv": return ","
    if fmt == "tsv": return "\t"
    raise DepMapIngestionError("unsupported_format", "declared dataset format is unsupported for tabular ingestion")


def _file_for(manifest: DepMapReleaseManifest, role: str):
    return next((item for item in manifest.file_manifests if item.dataset_role == role), None)


def _inspect_matrix(path: Path, fmt: str, role: str, parser_version: str) -> tuple[list[dict[str, Any]], set[str], int, int]:
    """Validate and index one matrix without retaining its numeric values.

    Matrices are inspected one at a time.  In subset mode, selected values are
    streamed in a later single-matrix pass after exact target resolution.
    """
    delimiter = _delimiter(fmt)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            header = next(reader, None)
            if not header or len(header) < 2 or header[0] != "ModelID":
                raise DepMapIngestionError("schema_mismatch", "matrix must have ModelID followed by gene columns")
            if len(set(header)) != len(header):
                raise DepMapIngestionError("schema_mismatch", "matrix header contains duplicate source labels")
            genes = []
            identity_counts: dict[str, int] = {}
            for index, label in enumerate(header[1:], 1):
                parsed = parse_gene_label(label, parser_version=parser_version)
                if parsed.canonical_identity:
                    identity_counts[parsed.canonical_identity] = identity_counts.get(parsed.canonical_identity, 0) + 1
                genes.append({"dataset_role": role, "source_column_index": index, **parsed.__dict__})
            for gene in genes:
                identity = GeneLabel(**{key: gene[key] for key in GeneLabel.__dataclass_fields__}).canonical_identity
                gene["canonical_identity"] = identity
                if identity and identity_counts[identity] > 1:
                    gene["parser_status"] = "duplicate_identity"
                    gene["limitation"] = "Duplicate canonical gene identity retained; columns were not merged."
            seen: set[str] = set()
            for number, values in enumerate(reader, 2):
                if len(values) != len(header):
                    raise DepMapIngestionError("parse_failure", f"matrix row width differs from header at source row {number}")
                model = values[0]
                if not model:
                    raise DepMapIngestionError("parse_failure", "matrix contains an empty ModelID")
                if model in seen:
                    raise DepMapIngestionError("parse_failure", "matrix contains duplicate ModelID")
                seen.add(model)
                for value in values[1:]:
                    if value == "":
                        continue
                    try: float(value)
                    except ValueError: raise DepMapIngestionError("parse_failure", "matrix contains an invalid numeric value") from None
    except DepMapIngestionError: raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise DepMapIngestionError("parse_failure", "matrix could not be parsed") from error
    if not seen:
        raise DepMapIngestionError("parse_failure", "matrix has no data rows")
    return genes, seen, len(header), len(seen)


def _stream_subset(path: Path, fmt: str, genes: list[dict[str, Any]], selected_labels: set[str], output: Path) -> None:
    """Materialize only selected source columns from one already-inspected matrix."""
    delimiter = _delimiter(fmt)
    selected = [index for index, gene in enumerate(genes) if gene["original_source_label"] in selected_labels]
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        with path.open("r", encoding="utf-8", newline="") as source, temporary.open("w", encoding="utf-8", newline="") as destination:
            reader = csv.reader(source, delimiter=delimiter)
            writer = csv.writer(destination, delimiter="\t", lineterminator="\n")
            header = next(reader, None)
            if header is None:
                raise DepMapIngestionError("parse_failure", "matrix has no header")
            writer.writerow(["ModelID"] + [genes[index]["original_source_label"] for index in selected])
            for values in reader:
                # The first inspection has already validated width and values;
                # retain blanks as blank TSV cells rather than zero-filling.
                writer.writerow([values[0]] + [values[index + 1] for index in selected])
        temporary.replace(output)
    except DepMapIngestionError:
        raise
    except OSError as error:
        raise DepMapIngestionError("output_failure", "derived subset artifact could not be written") from error


def _read_metadata(path: Path, fmt: str) -> tuple[dict[str, dict[str, str]], list[str]]:
    delimiter = _delimiter(fmt)
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            if not reader.fieldnames or "ModelID" not in reader.fieldnames:
                raise DepMapIngestionError("schema_mismatch", "metadata must contain ModelID")
            records: dict[str, dict[str, str]] = {}
            for number, row in enumerate(reader, 2):
                model = row.get("ModelID", "")
                if not model: raise DepMapIngestionError("parse_failure", "metadata contains an empty ModelID")
                if model in records: raise DepMapIngestionError("parse_failure", "metadata contains duplicate ModelID")
                records[model] = {key: (value or "") for key, value in row.items()}
                records[model]["source_row"] = str(number)
    except DepMapIngestionError: raise
    except (OSError, UnicodeError, csv.Error) as error: raise DepMapIngestionError("parse_failure", "metadata could not be parsed") from error
    return records, list(records)


def _resolve_targets(targets: Iterable[DepMapTargetRequest], genes_by_role: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    all_genes = [gene for genes in genes_by_role.values() for gene in genes]
    seen: set[tuple[str, str]] = set(); result = []
    for target in sorted(targets, key=lambda item: canonical_json(item.identity_payload())):
        key = (target.requested_identifier_type, target.normalized_request)
        if not target.is_valid:
            result.append({"requested_identifier": target.requested_identifier if isinstance(target.requested_identifier, str) else "",
                           "requested_identifier_type": target.requested_identifier_type if isinstance(target.requested_identifier_type, str) else "",
                           "normalized_request": target.normalized_request, "matched_source_column": None,
                           "matched_original_source_label": None, "resolution_status": "invalid_request",
                           "reason": "identifier must be a non-empty exact symbol or Entrez identifier",
                           "candidate_matches": []})
            continue
        candidates = [
            gene for gene in all_genes
            if (gene["parsed_symbol"] == key[1] if key[0] == "symbol" else gene["parsed_entrez_identifier"] == key[1])
        ]
        source_labels = sorted({gene["original_source_label"] for gene in candidates})
        if key in seen: status, reason = "duplicate_request", "same exact request appears more than once"
        elif len(source_labels) == 1: status, reason = ("resolved_exact_symbol" if key[0] == "symbol" else "resolved_exact_entrez"), "exact parsed identity match"
        elif len(source_labels) > 1: status, reason = "ambiguous", "more than one source column matches exact identity"
        else: status, reason = "unresolved", "no exact parsed identity match"
        seen.add(key)
        result.append({"requested_identifier": target.requested_identifier, "requested_identifier_type": target.requested_identifier_type,
                       "normalized_request": target.normalized_request, "matched_source_column": candidates[0]["source_column_index"] if len(source_labels) == 1 else None,
                       "matched_original_source_label": source_labels[0] if len(source_labels) == 1 else None,
                       "resolution_status": status, "reason": reason, "candidate_matches": source_labels})
    return result


def _write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="")
    temporary.replace(path)


def _tsv(rows: list[Mapping[str, Any]], fields: list[str]) -> str:
    output = []
    output.append("\t".join(fields))
    for row in rows:
        output.append("\t".join("" if row.get(field) is None else str(row.get(field)) for field in fields))
    return "\n".join(output) + "\n"


@dataclass(frozen=True)
class DepMapIngestionSnapshot:
    snapshot_format_version: str
    request_id: str
    release_manifest_id: str
    ingestion_mode: str
    parser_version: str
    mapping_version: str
    dataset_validation_results: Mapping[str, str]
    model_index_id: str
    gene_index_id: str
    target_universe_id: str | None
    target_resolution_coverage: tuple[Mapping[str, Any], ...]
    reconciliation_summary: Mapping[str, Any]
    source_counts: Mapping[str, Any]
    output_artifacts: tuple[str, ...]
    limitations: tuple[str, ...]
    terminal_status: str = "valid"

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_validation_results", _freeze(self.dataset_validation_results))
        object.__setattr__(self, "target_resolution_coverage", tuple(_freeze(item) for item in self.target_resolution_coverage))
        object.__setattr__(self, "reconciliation_summary", _freeze(self.reconciliation_summary))
        object.__setattr__(self, "source_counts", _freeze(self.source_counts))
        object.__setattr__(self, "output_artifacts", tuple(self.output_artifacts))
        object.__setattr__(self, "limitations", tuple(self.limitations))

    def identity_payload(self) -> dict[str, Any]:
        return {"snapshot_format_version": self.snapshot_format_version, "request_id": self.request_id,
                "release_manifest_id": self.release_manifest_id, "ingestion_mode": self.ingestion_mode,
                "parser_version": self.parser_version, "mapping_version": self.mapping_version,
                "dataset_validation_results": _thaw(self.dataset_validation_results), "model_index_id": self.model_index_id,
                "gene_index_id": self.gene_index_id, "target_universe_id": self.target_universe_id,
                "target_resolution_coverage": _thaw(self.target_resolution_coverage),
                "reconciliation_summary": _thaw(self.reconciliation_summary), "source_counts": _thaw(self.source_counts),
                "limitations": list(self.limitations), "terminal_status": self.terminal_status}

    @property
    def snapshot_id(self) -> str: return _identity("dmis", self.identity_payload())
    def to_dict(self) -> dict[str, Any]: return {**self.identity_payload(), "snapshot_id": self.snapshot_id, "output_artifacts": list(self.output_artifacts)}


def ingest_local_release(request: DepMapIngestionRequest) -> DepMapIngestionSnapshot:
    """Validate, normalize, and write deterministic artifacts from local files only."""
    # Reuse the Issue 501 validator; its layout is operational and excluded from identity.
    layout = DepMapLocalLayoutRequest("v0.5.0", request.data_root, request.release_manifest.release_identifier,
                                     request.output_directory.parent, "read_only", request.operational_actor or "local-ingestion")
    validation = validate_local_release(request.release_manifest, layout, source_root=request.data_root)
    if not validation.is_valid: raise DepMapIngestionError(validation.status, validation.errors[0])
    if request.output_directory.resolve() == request.data_root.resolve() or request.data_root.resolve() in request.output_directory.resolve().parents:
        raise DepMapIngestionError("output_failure", "output directory cannot be inside raw source root")
    request.output_directory.mkdir(parents=True, exist_ok=True)
    # Keep only structural indexes in memory.  In particular, never retain a
    # complete row/value matrix, let alone both production matrices at once.
    matrices: dict[str, tuple[list[dict[str, Any]], set[str], int, int]] = {}
    for role in MATRIX_ROLES:
        item = _file_for(request.release_manifest, role)
        if item is None:
            continue
        matrices[role] = _inspect_matrix(request.data_root / item.relative_filename, item.file_format, role, request.parser_version)
    if "crispr_gene_effect" not in matrices:
        raise DepMapIngestionError("missing_required_role", "gene-effect matrix is required for ingestion")
    metadata_item = _file_for(request.release_manifest, "model_metadata")
    if metadata_item is None: raise DepMapIngestionError("missing_required_role", "model metadata is required for ingestion")
    metadata, metadata_order = _read_metadata(request.data_root / metadata_item.relative_filename, metadata_item.file_format)
    genes_by_role = {role: value[0] for role, value in matrices.items()}
    resolutions = _resolve_targets(request.target_universe or (), genes_by_role)
    effect_models = matrices["crispr_gene_effect"][1]
    prob_models = matrices.get("crispr_dependency_probability", ([], set(), 0, 0))[1]
    effect_genes = {gene["canonical_identity"] or f"raw:{gene['original_source_label']}" for gene in genes_by_role["crispr_gene_effect"]}
    prob_genes = {gene["canonical_identity"] or f"raw:{gene['original_source_label']}" for gene in genes_by_role.get("crispr_dependency_probability", [])}
    reconciliation = {"models_shared": len(effect_models & prob_models), "models_only_gene_effect": len(effect_models - prob_models),
                      "models_only_dependency_probability": len(prob_models - effect_models), "models_missing_metadata": len((effect_models | prob_models) - set(metadata)),
                      "metadata_models_absent_from_matrices": len(set(metadata) - (effect_models | prob_models)), "genes_shared": len(effect_genes & prob_genes),
                      "genes_only_gene_effect": len(effect_genes - prob_genes), "genes_only_dependency_probability": len(prob_genes - effect_genes),
                      "malformed_or_ambiguous_gene_columns": sum(g["parser_status"] != "parsed" for gs in genes_by_role.values() for g in gs)}
    gene_rows = [gene for role in sorted(genes_by_role) for gene in genes_by_role[role]]
    gene_rows.sort(key=lambda row: (row["dataset_role"], row["source_column_index"]))
    model_rows = []
    for model in sorted(effect_models | prob_models | set(metadata)):
        record = metadata.get(model, {})
        model_rows.append({"model_identifier": model, "presence_in_gene_effect": model in effect_models, "presence_in_dependency_probability": model in prob_models,
                           "presence_in_metadata": model in metadata, "metadata_mapping_status": "mapped" if model in metadata else "metadata_absent",
                           "source_provenance": f"metadata_row:{record.get('source_row', '')}" if record else ""})
    selected_labels = {r["matched_original_source_label"] for r in resolutions if r["resolution_status"].startswith("resolved_")}
    artifacts = ["coverage_summary.json", "gene_index.tsv", "ingestion_snapshot.json", "model_index.tsv"]
    if request.ingestion_mode == "target_subset": artifacts += ["gene_effect_subset.tsv", "dependency_probability_subset.tsv"]
    source_counts = {role: {"rows": row_count, "columns": width} for role, (_, _, width, row_count) in matrices.items()}
    resolved_labels_by_role = {
        role: {gene["original_source_label"] for gene in genes}
        for role, genes in genes_by_role.items()
    }
    coverage = {"requested_target_count": len(request.target_universe or ()), "unique_requested_target_count": len({(x.requested_identifier_type, x.normalized_request) for x in request.target_universe or ()}),
                "resolved_target_count": sum(r["resolution_status"].startswith("resolved_") for r in resolutions), "unresolved_target_count": sum(r["resolution_status"] == "unresolved" for r in resolutions),
                "ambiguous_target_count": sum(r["resolution_status"] == "ambiguous" for r in resolutions),
                "gene_effect_coverage": sum(r["matched_original_source_label"] in resolved_labels_by_role.get("crispr_gene_effect", set()) for r in resolutions if r["resolution_status"].startswith("resolved_")),
                "dependency_probability_coverage": sum(r["matched_original_source_label"] in resolved_labels_by_role.get("crispr_dependency_probability", set()) for r in resolutions if r["resolution_status"].startswith("resolved_")),
                "model_counts": {"gene_effect": len(effect_models), "dependency_probability": len(prob_models), "metadata": len(metadata)}, "reconciliation_counts": reconciliation,
                "optional_dataset_role_availability": {role: _file_for(request.release_manifest, role) is not None for role in request.release_manifest.optional_dataset_roles},
                "limitation": "Coverage records exact file identity matches only; it does not assert biological evidence quality."}
    gene_id = _identity("dmgi", {"rows": gene_rows}); model_id = _identity("dmmi", {"rows": model_rows})
    snapshot = DepMapIngestionSnapshot(INGESTION_SNAPSHOT_FORMAT_VERSION, request.request_id, request.release_manifest.manifest_id, request.ingestion_mode,
                                      request.parser_version, request.mapping_version, {item.dataset_role: "valid" for item in request.release_manifest.file_manifests},
                                      model_id, gene_id, request.target_universe_id, tuple(resolutions), reconciliation, source_counts, tuple(sorted(artifacts)),
                                      tuple(request.release_manifest.release_limitations) + tuple(request.limitations))
    try:
        _write(request.output_directory / "gene_index.tsv", _tsv(gene_rows, ["dataset_role", "source_column_index", "original_source_label", "parsed_symbol", "parsed_entrez_identifier", "parser_status", "canonical_identity", "limitation"]))
        _write(request.output_directory / "model_index.tsv", _tsv(model_rows, ["model_identifier", "presence_in_gene_effect", "presence_in_dependency_probability", "presence_in_metadata", "metadata_mapping_status", "source_provenance"]))
        _write(request.output_directory / "coverage_summary.json", canonical_json(coverage) + "\n")
        if request.ingestion_mode == "target_subset":
            for role, filename in (("crispr_gene_effect", "gene_effect_subset.tsv"), ("crispr_dependency_probability", "dependency_probability_subset.tsv")):
                matrix = matrices.get(role)
                if matrix is None:
                    _write(request.output_directory / filename, "ModelID\n")
                    continue
                item = _file_for(request.release_manifest, role)
                assert item is not None
                _stream_subset(request.data_root / item.relative_filename, item.file_format, matrix[0], selected_labels,
                               request.output_directory / filename)
        _write(request.output_directory / "ingestion_snapshot.json", canonical_json(snapshot.to_dict()) + "\n")
    except OSError as error:
        raise DepMapIngestionError("output_failure", "derived artifact could not be written") from error
    return snapshot
