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
