"""Release-pinned, offline contracts for future DepMap functional-dependency work.

This package is intentionally limited to manifests and small-file validation.
It does not retrieve, parse, score, rank, classify, or interpret dependency data.
"""

from .depmap_models import (
    DepMapFileManifest,
    DepMapLocalLayoutRequest,
    DepMapReleaseManifest,
    DepMapSchemaFingerprint,
)
from .depmap_validation import DepMapManifestValidationResult, validate_local_release
from .depmap_ingestion import (
    DepMapIngestionError, DepMapIngestionRequest, DepMapIngestionSnapshot,
    DepMapTargetRequest, ingest_local_release, parse_gene_label,
)

__all__ = [
    "DepMapFileManifest",
    "DepMapLocalLayoutRequest",
    "DepMapManifestValidationResult",
    "DepMapReleaseManifest",
    "DepMapSchemaFingerprint",
    "validate_local_release",
    "DepMapIngestionError",
    "DepMapIngestionRequest",
    "DepMapIngestionSnapshot",
    "DepMapTargetRequest",
    "ingest_local_release",
    "parse_gene_label",
]
