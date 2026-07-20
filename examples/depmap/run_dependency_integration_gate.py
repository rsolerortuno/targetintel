#!/usr/bin/env python3
"""Run the offline Issue 506 dependency-integration gate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from targetintel.functional_dependency import (
    DependencyIntegrationError, DependencyIntegrationPolicy,
    build_dependency_integration, write_dependency_integration_artifacts,
)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-dir", required=True)
    parser.add_argument("--baseline-ranking", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--evidence-scope", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        policy = DependencyIntegrationPolicy.from_dict(json.loads(Path(args.policy).read_text(encoding="utf-8")))
        result = build_dependency_integration(Path(args.benchmark_dir).resolve(), Path(args.baseline_ranking).resolve(), policy, json.loads(Path(args.context).read_text(encoding="utf-8")), args.evidence_scope)
        write_dependency_integration_artifacts(Path(args.output_dir).resolve(), result)
    except (DependencyIntegrationError, ValueError) as error:
        parser.error(str(error))
    print(result["decision"]["decision_id"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
