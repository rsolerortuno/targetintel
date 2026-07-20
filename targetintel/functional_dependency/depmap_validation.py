"""Small-fixture, fail-closed validation for DepMap release manifests.

Only file presence, bytes, checksums, and one text header are inspected.  This
module deliberately contains no downloader or complete matrix parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .depmap_models import DepMapLocalLayoutRequest, DepMapReleaseManifest


VALIDATION_STATUSES = frozenset({"valid", "invalid_manifest", "missing_required_role", "missing_file", "checksum_mismatch", "size_mismatch", "schema_mismatch", "release_mismatch", "unsupported_format", "invalid_path", "validation_failed"})


@dataclass(frozen=True)
class DepMapManifestValidationResult:
    status: str
    manifest_id: str | None
    release_identifier: str | None
    dataset_role: str | None
    errors: tuple[str, ...] | list[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "errors", tuple(self.errors))
        if self.status not in VALIDATION_STATUSES:
            raise ValueError("unknown manifest validation status")
        if any(not isinstance(item, str) or not item for item in self.errors):
            raise ValueError("validation errors must be sanitized non-empty strings")

    @property
    def is_valid(self) -> bool:
        return self.status == "valid"


def _result(status: str, manifest: DepMapReleaseManifest, role: str | None, error: str) -> DepMapManifestValidationResult:
    return DepMapManifestValidationResult(status, manifest.manifest_id, manifest.release_identifier, role, (error,))


def _header_matches(path: Path, file_format: str, fingerprint) -> bool:
    if file_format == "text":
        return fingerprint.identifier_orientation == "release_document"
    delimiter = "," if file_format == "csv" else "\t" if file_format == "tsv" else None
    if delimiter is None:
        return False
    with path.open("r", encoding="utf-8", newline="") as handle:
        header = handle.readline().rstrip("\r\n").split(delimiter)
    return all(column in header for column in fingerprint.canonical_required_columns)


def validate_local_release(manifest: DepMapReleaseManifest, layout: DepMapLocalLayoutRequest, *, expected_release_identifier: str | None = None) -> DepMapManifestValidationResult:
    """Validate only local small fixtures; this result never asserts gene coverage or biology."""
    if expected_release_identifier is not None and expected_release_identifier != manifest.release_identifier:
        return _result("release_mismatch", manifest, None, "explicit expected release identifier does not match manifest")
    if layout.release_directory != manifest.release_identifier:
        return _result("release_mismatch", manifest, None, "layout release directory does not match manifest release identifier")
    for file_manifest in manifest.file_manifests:
        path = layout.local_release_root / file_manifest.relative_filename
        if not path.is_file():
            return _result("missing_file", manifest, file_manifest.dataset_role, "declared local file is absent")
        if path.stat().st_size != file_manifest.expected_size_bytes:
            return _result("size_mismatch", manifest, file_manifest.dataset_role, "local file size differs from manifest")
        digest = sha256(path.read_bytes()).hexdigest()
        if digest != file_manifest.sha256_checksum:
            return _result("checksum_mismatch", manifest, file_manifest.dataset_role, "local file checksum differs from manifest")
        try:
            matches = _header_matches(path, file_manifest.file_format, file_manifest.schema_fingerprint)
        except (OSError, UnicodeError):
            return _result("validation_failed", manifest, file_manifest.dataset_role, "local file could not be read as its declared format")
        if not matches:
            return _result("schema_mismatch", manifest, file_manifest.dataset_role, "local file header does not satisfy schema fingerprint")
    return DepMapManifestValidationResult("valid", manifest.manifest_id, manifest.release_identifier, None)
