#!/usr/bin/env python3
"""Run local, release-pinned DepMap ingestion without network access."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys

# Permit direct execution from a checkout without importing an installed copy.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from targetintel.functional_dependency import (
    DepMapIngestionError, DepMapIngestionRequest, DepMapReleaseManifest,
    DepMapTargetRequest, ingest_local_release,
)
from targetintel.functional_dependency.depmap_ingestion import INGESTION_REQUEST_FORMAT_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--mode", required=True, choices=("target_subset", "full_matrix"))
    parser.add_argument("--targets")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.mode == "target_subset" and not args.targets:
        parser.error("--targets is required in target_subset mode")
    if args.mode == "full_matrix" and args.targets:
        parser.error("--targets is not allowed in full_matrix mode")
    manifest = DepMapReleaseManifest.from_dict(json.loads(Path(args.manifest).read_text(encoding="utf-8")))
    targets = None
    if args.targets:
        with Path(args.targets).open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            targets = [DepMapTargetRequest(row.get("requested_identifier", ""), row.get("requested_identifier_type", "")) for row in reader]
    request = DepMapIngestionRequest(INGESTION_REQUEST_FORMAT_VERSION, manifest, args.mode,
                                     Path(args.data_root).resolve(), Path(args.output_dir).resolve(), target_universe=targets)
    try:
        snapshot = ingest_local_release(request)
    except DepMapIngestionError as error:
        parser.error(f"{error.status}: {error}")
    print(snapshot.snapshot_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
