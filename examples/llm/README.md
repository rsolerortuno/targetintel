# v0.3.0 offline mock demo

Run the complete synthetic, research-only workflow with no network, model server,
credentials, or Obsidian installation:

```bash
python examples/llm/run_v030_mock_demo.py --output-dir /tmp/targetintel-v030-demo
```

The caller-selected directory receives auditable JSON artifacts, a private demo
DuckDB store, and an exported Markdown note under `obsidian-vault/`. It uses only
`MockProvider`; all identifiers and scientific content are synthetic. Human review
is explicitly represented as controlled software promotion, never scientific or
clinical validation. Re-running the same output is safe for the export's
same-content idempotency check; use a clean directory to compare identities.
