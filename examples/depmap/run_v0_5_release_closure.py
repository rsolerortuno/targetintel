#!/usr/bin/env python3
"""Run the local-only v0.5.0 DepMap release-closure workflow."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from targetintel.functional_dependency import ReleaseClosureError, V050ReleaseRunConfiguration, run_release_closure

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-config", required=True)
    parser.add_argument("--evidence-classification", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        configuration = V050ReleaseRunConfiguration.from_file(args.run_config)
        result = run_release_closure(configuration, args.evidence_classification, Path(args.output_dir))
    except ReleaseClosureError as error:
        parser.error(str(error))
    print(result["terminal_state"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
