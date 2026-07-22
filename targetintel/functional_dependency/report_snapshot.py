"""Portable, fail-closed export of a completed DepMap release closure.

This module deliberately reads only small closure artifacts and selected
profile records.  It performs no DepMap calculation, ranking, or activation.
"""
from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping


DEFAULT_SELECTED_TARGETS = (
    "CTLA4", "PDCD1", "CD274", "LAG3", "B2M", "JAK1", "JAK2", "BRAF",
    "PTEN", "MITF", "TERT", "IL2RA", "GNAQ", "GNA11",
)
_OUTPUT_NAMES = (
    "README.md", "release_summary.json", "release_report.md", "benchmark_report.md",
    "integration_report.md", "candidate_overlay.tsv", "dependency_profile_summary.tsv",
    "selected_target_profiles.tsv", "checksums.json",
)
_INPUT_NAMES = (
    "release_preflight.json", "artifact_compatibility.json", "release_readiness.json",
    "reproducibility_summary.json", "release_report.md", "release_closure_manifest.json",
    "activation_readiness_summary.json", "profiles/dependency_profile_summary.tsv",
    "profiles/dependency_profiles.jsonl", "integration/candidate_overlay.tsv",
    "integration/baseline_preservation.json", "integration/integration_gate_decision.json",
    "integration/activation_readiness.json", "integration/integration_report.md",
    "benchmark/benchmark_report.md", "benchmark/benchmark_coverage.json",
    "manifests/real-v6-release-closure-summary.json",
    "manifests/real-v6-run-a-vs-run-b-reproducibility.json",
)
_PATH_LEAK = re.compile(r"(?:/home/|/media/|/mnt/|/tmp/|/Users/|/Volumes/|[A-Za-z]:[\\/])")
_PATH_VALUE = re.compile(r"(?:[A-Za-z]:[\\/][^\s`'\"<>]+|/(?:home|media|mnt|tmp|Users|Volumes)/[^\s`'\"<>]+)")


class DepMapReportSnapshotError(ValueError):
    """A sanitized validation or publication failure."""


def _fail(message: str) -> None:
    raise DepMapReportSnapshotError(message)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DepMapReportSnapshotError("required JSON artifact is malformed") from error
    if not isinstance(value, dict):
        _fail("required JSON artifact must be an object")
    return value


def _need(value: Mapping[str, Any], key: str, expected: Any = None) -> Any:
    if key not in value:
        _fail("required release invariant is missing: " + key)
    result = value[key]
    if expected is not None and result != expected:
        _fail("release invariant failed: " + key)
    return result


def _one_of(values: Iterable[Any], label: str) -> Any:
    present = [value for value in values if value is not None]
    if not present or any(value != present[0] for value in present):
        _fail("incompatible " + label)
    return present[0]


def _safe_text(text: str) -> str:
    return _PATH_VALUE.sub("[local path removed]", text)


def _validate_no_paths(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_file() and _PATH_LEAK.search(path.read_text(encoding="utf-8")):
            _fail("portable output contains a local path")


def _copy_text(source: Path, destination: Path) -> None:
    destination.write_text(_safe_text(source.read_text(encoding="utf-8")), encoding="utf-8", newline="")


def _profile_rows(jsonl_path: Path, selected: tuple[str, ...]) -> list[dict[str, str]]:
    """Read the profile JSONL exactly once, retaining selected records only."""
    found: dict[str, Mapping[str, Any]] = {}
    try:
        with jsonl_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                target = record.get("target_identity", {}).get("normalized_request")
                if target in selected and target not in found:
                    found[target] = record
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as error:
        raise DepMapReportSnapshotError("dependency profile JSONL is malformed") from error
    rows: list[dict[str, str]] = []
    for target in selected:
        record = found.get(target)
        if record is None:
            rows.append({"target": target, "coverage_status": "not_available"})
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            _fail("selected dependency profile lacks a payload")
        summaries = payload.get("summaries", {})
        context = summaries.get("context", {}) if isinstance(summaries, Mapping) else {}
        effect = context.get("gene_effect", {}) if isinstance(context, Mapping) else {}
        probability = context.get("dependency_probability", {}) if isinstance(context, Mapping) else {}
        coverage = payload.get("model_coverage", {})
        row = {
            "target": target,
            "resolution_status": str(payload.get("target_resolution_status", "")),
            "coverage_status": str(payload.get("coverage_status", "")),
            "profile_status": str(record.get("terminal_status", "")),
            "context_model_count": str(coverage.get("context_model_count", "")) if isinstance(coverage, Mapping) else "",
            "context_gene_effect_median": str(effect.get("median", "")),
            "context_dependency_probability_median": str(probability.get("median", "")),
            "limitations": json.dumps(payload.get("limitations", []), sort_keys=True, separators=(",", ":")),
        }
        rows.append(row)
    return rows


def _write_tsv(path: Path, fields: list[str], rows: list[Mapping[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fields} for row in rows])


def _validate_paths(run: Path, config: Path, manifests: Path, output: Path) -> None:
    for path, label in ((run, "run_dir"), (config, "config_dir"), (manifests, "manifest_dir")):
        if not path.is_dir():
            _fail(label + " must be an existing directory")
    for input_dir in (run, config, manifests):
        if output == input_dir or output.is_relative_to(input_dir) or input_dir.is_relative_to(output):
            _fail("output directory overlaps an input directory")
    if output == Path("/") or output == Path.cwd().resolve() or output.is_symlink():
        _fail("unsafe output directory")


def _configuration_id(config_dir: Path) -> str:
    """Obtain a declared identity without exposing configuration contents."""
    identity_file = config_dir / "release_configuration_identity.json"
    if identity_file.is_file():
        value = _need(_json(identity_file), "configuration_id")
        if not isinstance(value, str) or not value:
            _fail("configuration identity is malformed")
        return value
    # The actual release configuration is read only to validate its derived
    # identity; it is never copied because it can contain local paths.
    real_config = config_dir / "real_run_config.json"
    if real_config.is_file():
        try:
            from .release_closure import V050ReleaseRunConfiguration
            return V050ReleaseRunConfiguration.from_file(real_config).configuration_id
        except (ValueError, OSError) as error:
            raise DepMapReportSnapshotError("release configuration identity is invalid") from error
    _fail("configuration identity artifact is missing")


def export_depmap_report_snapshot(*, run_dir: Path | str, config_dir: Path | str,
                                  manifest_dir: Path | str, output_dir: Path | str,
                                  selected_targets: Iterable[str] = DEFAULT_SELECTED_TARGETS,
                                  overwrite: bool = False) -> dict[str, Any]:
    """Export a deterministic, repository-safe derived release snapshot."""
    raw_output = Path(output_dir).absolute()
    if any(part.is_symlink() for part in (raw_output, *raw_output.parents)):
        _fail("unsafe output directory")
    run, config, manifests, output = (Path(value).resolve() for value in (run_dir, config_dir, manifest_dir, raw_output))
    selected = tuple(selected_targets)
    if not selected or any(not isinstance(item, str) or not item for item in selected) or len(set(selected)) != len(selected):
        _fail("selected targets must be unique non-empty symbols")
    _validate_paths(run, config, manifests, output)
    sources = {name: (manifests / name[10:] if name.startswith("manifests/") else run / name) for name in _INPUT_NAMES}
    if any(not path.is_file() for path in sources.values()):
        _fail("a required release artifact is missing")
    preflight, compatibility, readiness = (_json(sources[name]) for name in ("release_preflight.json", "artifact_compatibility.json", "release_readiness.json"))
    reproducibility, closure, activation = (_json(sources[name]) for name in ("reproducibility_summary.json", "release_closure_manifest.json", "activation_readiness_summary.json"))
    baseline, gate, candidate_readiness = (_json(sources[name]) for name in ("integration/baseline_preservation.json", "integration/integration_gate_decision.json", "integration/activation_readiness.json"))
    coverage, closure_summary, external = (_json(sources[name]) for name in ("benchmark/benchmark_coverage.json", "manifests/real-v6-release-closure-summary.json", "manifests/real-v6-run-a-vs-run-b-reproducibility.json"))
    _need(preflight, "status", "passed"); _need(preflight, "release_identifier", "DepMap_Public_26Q1")
    _need(compatibility, "compatible", True); _need(compatibility, "expected_context_identity", "melanoma_anti_pd1:v1")
    configuration_id = _one_of((_configuration_id(config), _need(preflight, "configuration_id"), _need(readiness, "configuration_id"), _need(closure, "configuration_id"), reproducibility.get("configuration_id"), closure_summary.get("configuration_id")), "configuration IDs")
    manifest_id = _one_of((_need(preflight, "release_manifest_id"), closure_summary.get("release_manifest_id"), external.get("release_manifest_id")), "release manifest IDs")
    scientific_identity = _one_of((closure_summary.get("scientific_closure_identity"), external.get("scientific_closure_identity")), "scientific closure identities")
    if not scientific_identity:
        _fail("scientific closure identity is missing")
    _need(reproducibility, "result", "reproducible")
    if _need(reproducibility, "differing_artifacts") != []: _fail("internal differing artifacts are not empty")
    _need(external, "result", "reproducible")
    if external.get("differing_scientific_artifacts", external.get("differing_artifacts")) != []: _fail("external differing scientific artifacts are not empty")
    _need(closure, "successful_closure", True); _need(readiness, "release_state", "ready_research_preview_human_review")
    for key in ("baseline_file_bytes_unchanged", "baseline_scores_retained_exactly", "baseline_ranks_retained_exactly", "production_scoring_configurations_unchanged", "production_ranking_configurations_unchanged"):
        _need(baseline, key, True)
    _need(readiness, "production_activation_enabled", False); _need(closure, "production_activation_enabled", False); _need(gate, "production_activation_enabled", False)
    _need(activation, "approved_authorization_emitted", False); _need(candidate_readiness, "status", "blocked")
    if not str(_need(gate, "decision_state")).startswith("blocked"):
        _fail("integration state is not blocked")
    _need(readiness, "human_review_required", True); _need(activation, "human_review_required", True); _need(gate, "human_review_required", True); _need(candidate_readiness, "human_review_required", True)
    if output.exists() and not overwrite: _fail("output directory already exists")
    if output.exists() and (not output.is_dir() or output.is_symlink()): _fail("unsafe existing output directory")
    parent = output.parent
    temporary = Path(tempfile.mkdtemp(prefix=".depmap-report-snapshot-", dir=parent))
    try:
        _copy_text(sources["release_report.md"], temporary / "release_report.md")
        _copy_text(sources["benchmark/benchmark_report.md"], temporary / "benchmark_report.md")
        _copy_text(sources["integration/integration_report.md"], temporary / "integration_report.md")
        shutil.copyfile(sources["integration/candidate_overlay.tsv"], temporary / "candidate_overlay.tsv")
        shutil.copyfile(sources["profiles/dependency_profile_summary.tsv"], temporary / "dependency_profile_summary.tsv")
        profile_fields = ["target", "resolution_status", "coverage_status", "profile_status", "context_model_count", "context_gene_effect_median", "context_dependency_probability_median", "limitations"]
        profiles = _profile_rows(sources["profiles/dependency_profiles.jsonl"], selected)
        _write_tsv(temporary / "selected_target_profiles.tsv", profile_fields, profiles)
        metrics = compatibility.get("metrics", {})
        summary = {"snapshot_format_version": "v1", "release_identifier": "DepMap_Public_26Q1", "release_manifest_id": manifest_id, "configuration_id": configuration_id, "scientific_closure_identity": scientific_identity, "context_identity": "melanoma_anti_pd1:v1", "release_state": readiness["release_state"], "preflight_status": preflight["status"], "artifact_compatibility": True, "internal_reproducibility": reproducibility["result"], "external_reproducibility": external["result"], "differing_scientific_artifact_count": 0, "baseline_preserved": True, "production_activation_enabled": False, "approved_authorization_emitted": False, "human_review_required": True, "integration_state": activation.get("integration_state"), "candidate_activation_readiness": candidate_readiness["status"], "background_count": metrics.get("background_count"), "discovery_count": metrics.get("discovery_count"), "benchmark_count": coverage.get("total_benchmark_targets", metrics.get("benchmark_count")), "benchmark_coverage": coverage.get("benchmark_coverage", metrics.get("benchmark_coverage")), "holdout_coverage": metrics.get("holdout_coverage"), "unresolved_count": metrics.get("unresolved_count"), "selected_targets": list(selected), "missing_selected_targets": [row["target"] for row in profiles if row["coverage_status"] == "not_available"], "limitations": readiness.get("limitations", []), "source_artifact_names": sorted(_INPUT_NAMES)}
        (temporary / "release_summary.json").write_text(json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="")
        readme = "# Portable DepMap report snapshot\n\nThis repository-safe derived snapshot records `DepMap_Public_26Q1` for melanoma anti-PD-1 context (`melanoma_anti_pd1:v1`). Configuration identity: `" + configuration_id + "`. Release manifest identity: `" + manifest_id + "`. Scientific closure identity: `" + scientific_identity + "`.\n\nThe original productive baseline contains 300 genes and remains unchanged. The discovery universe contains 331 identities; 18,531 genes were used only as background, and no 18,531-gene productive ranking was generated. Production activation is disabled and human review is mandatory.\n\nDepMap cell-line dependency is not clinical anti-PD-1 response evidence. Absence of tumor-cell dependency does not invalidate an immune target. General dependency may reflect broad essentiality, and cell lines do not reproduce the full tumor microenvironment. Full matrices and `dependency_profiles.jsonl` are excluded.\n\nFiles: `release_summary.json` records validated closure state; the three Markdown reports preserve sanitized aggregate reports; `candidate_overlay.tsv` and `dependency_profile_summary.tsv` are derived aggregate tables; `selected_target_profiles.tsv` contains only requested descriptive profiles; `checksums.json` verifies the other eight files.\n"
        (temporary / "README.md").write_text(readme, encoding="utf-8", newline="")
        _validate_no_paths(temporary)
        records = [{"name": name, "sha256": sha256((temporary / name).read_bytes()).hexdigest(), "byte_size": (temporary / name).stat().st_size} for name in sorted(_OUTPUT_NAMES[:-1])]
        (temporary / "checksums.json").write_text(json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="")
        _validate_no_paths(temporary)
        if output.exists(): shutil.rmtree(output)
        temporary.replace(output)
        return summary
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
