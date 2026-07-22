"""Command-line wrapper for the portable DepMap release snapshot exporter."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

# Permit direct invocation from a source checkout without an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from targetintel.functional_dependency.report_snapshot import DEFAULT_SELECTED_TARGETS, DepMapReportSnapshotError, export_depmap_report_snapshot

def main() -> int:
    parser = argparse.ArgumentParser(description="Export a portable DepMap release snapshot.")
    parser.add_argument("--run-dir", required=True); parser.add_argument("--config-dir", required=True)
    parser.add_argument("--manifest-dir", required=True); parser.add_argument("--output-dir", required=True)
    parser.add_argument("--selected-target", action="append", dest="selected_targets")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        summary = export_depmap_report_snapshot(run_dir=args.run_dir, config_dir=args.config_dir, manifest_dir=args.manifest_dir, output_dir=args.output_dir, selected_targets=tuple(args.selected_targets or DEFAULT_SELECTED_TARGETS), overwrite=args.overwrite)
    except DepMapReportSnapshotError as error:
        parser.error(str(error))
    print("Exported portable DepMap snapshot: " + summary["release_identifier"] + "; selected targets: " + str(len(summary["selected_targets"])))
    return 0
if __name__ == "__main__": raise SystemExit(main())
