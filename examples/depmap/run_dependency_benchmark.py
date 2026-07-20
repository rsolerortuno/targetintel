#!/usr/bin/env python3
"""Run the offline, analysis-only Issue 505 dependency benchmark."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from targetintel.functional_dependency import (
    DependencyBenchmarkError, DependencyBenchmarkPolicy,
    evaluate_dependency_benchmark, write_dependency_benchmark_artifacts,
)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-dir", required=True)
    parser.add_argument("--profiles-dir", required=True)
    parser.add_argument("--baseline-ranking", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        policy = DependencyBenchmarkPolicy.from_dict(json.loads(Path(args.policy).read_text(encoding="utf-8")))
        evaluation = evaluate_dependency_benchmark(Path(args.universe_dir).resolve(), Path(args.profiles_dir).resolve(), Path(args.baseline_ranking).resolve(), policy)
        write_dependency_benchmark_artifacts(Path(args.output_dir).resolve(), evaluation, policy)
    except (DependencyBenchmarkError, ValueError) as error:
        parser.error(str(error))
    print(evaluation.manifest["policy_id"])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
