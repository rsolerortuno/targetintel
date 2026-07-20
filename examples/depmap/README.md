# Local DepMap ingestion

This entry point validates explicitly supplied local files and produces only
normalized indexes and, in subset mode, exact requested columns. It does not
download data or calculate biological dependency, melanoma selectivity, scores,
or rankings.

Synthetic CI fixture:

```bash
python examples/depmap/run_local_ingestion.py \
  --manifest tests/fixtures/depmap/ingestion/release_manifest.json \
  --data-root tests/fixtures/depmap/ingestion \
  --mode target_subset \
  --targets tests/fixtures/depmap/ingestion/target_subset.tsv \
  --output-dir /tmp/targetintel-depmap-output
```

For a real local release, provide files you have obtained and stored locally;
TargetIntel-IO does not bundle DepMap matrices:

```bash
python examples/depmap/run_local_ingestion.py \
  --manifest /path/to/release_manifest.json \
  --data-root /path/to/local/release-files \
  --mode full_matrix \
  --output-dir /path/to/derived-output
```

## Descriptive dependency profiles

After successful subset ingestion, build a separate, descriptive profile with
explicit structured context and policy contracts. This path never changes
target scores or rankings and makes no clinical or therapeutic conclusion.

```bash
python examples/depmap/run_dependency_profiles.py \
  --ingestion-dir /tmp/targetintel-depmap-output \
  --context tests/fixtures/depmap/profiles/melanoma_context.json \
  --policy tests/fixtures/depmap/profiles/profile_policy.json \
  --output-dir /tmp/targetintel-depmap-profiles
```

It writes a profile manifest, deterministic JSONL profiles, a review TSV,
coverage summary, and a model-context index. The bundled fixtures are
synthetic and non-biological.

## Universe freeze

After full-matrix ingestion, freeze the benchmark, pre-DepMap discovery and
background universes with `run_universe_freeze.py`. It writes only canonical
universe metadata, overlap and leakage-audit artifacts; it never scores, ranks
or profiles targets.

## Analysis-only dependency benchmark

Issue 505 compares an explicit unchanged baseline artifact with a dependency
diagnostic order and a bounded within-band overlay. It is offline and analysis
only: it never changes TargetIntel scores, ranks, roles, configuration, or
selection. The fixture is synthetic and supports no melanoma finding.

```bash
python examples/depmap/run_dependency_benchmark.py \
  --universe-dir /tmp/targetintel-depmap-universes \
  --profiles-dir /tmp/targetintel-depmap-profiles \
  --baseline-ranking tests/fixtures/depmap/benchmark/baseline_ranking.tsv \
  --policy tests/fixtures/depmap/benchmark/evaluation_policy.json \
  --output-dir /tmp/targetintel-dependency-benchmark
```

## Dependency integration gate

Issue 506 consumes that benchmark only through an explicit, offline gate. It
writes an analysis-only candidate overlay and never changes production scores,
ranks, defaults, or CLI behavior. The synthetic fixture is always blocked;
human authorization is not emitted.

```bash
python examples/depmap/run_dependency_integration_gate.py \
  --benchmark-dir /tmp/targetintel-dependency-benchmark \
  --baseline-ranking tests/fixtures/depmap/benchmark/baseline_ranking.tsv \
  --policy tests/fixtures/depmap/integration/integration_policy.json \
  --context tests/fixtures/depmap/integration/context.json \
  --evidence-scope synthetic_fixture \
  --output-dir /tmp/targetintel-dependency-integration
```
