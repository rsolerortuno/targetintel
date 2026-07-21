"""Offline, fail-closed v0.5.0 functional-dependency release closure.

This module is deliberately an orchestration and evidence-accounting boundary.
It does not alter TargetIntel scoring, rankings, roles, or defaults.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping
from urllib.parse import urlparse

from .depmap_models import (DepMapLocalLayoutRequest, DepMapReleaseManifest,
    LOCAL_LAYOUT_REQUEST_FORMAT_VERSION, canonical_json, _forbidden_nested, _identity)
from .depmap_validation import validate_local_release
from .depmap_ingestion import (INGESTION_REQUEST_FORMAT_VERSION,
    DepMapIngestionRequest, DepMapTargetRequest, ingest_local_release)
from .depmap_profiles import (DepMapModelContextDefinition,
    FunctionalDependencyProfilePolicy, build_dependency_profiles,
    write_dependency_profile_artifacts)
from .target_universes import freeze_universes
from .depmap_benchmark import (DependencyBenchmarkPolicy,
    evaluate_dependency_benchmark, write_dependency_benchmark_artifacts,
    load_baseline_ranking)
from .dependency_integration import (DependencyIntegrationPolicy,
    build_dependency_integration, write_dependency_integration_artifacts)

FORMAT_VERSION = "v0.5.0"
EVIDENCE_CLASSIFICATIONS = frozenset({"synthetic_fixture", "local_real_public_release", "externally_validated_real_release"})
RELEASE_STATES = frozenset({"blocked_fixture_evidence", "blocked_missing_real_data", "blocked_invalid_real_data", "blocked_incompatible_artifacts", "blocked_incomplete_universe", "blocked_benchmark_failure", "blocked_nonreproducible", "ready_research_preview_human_review", "ready_optional_candidate_human_review", "explicitly_rejected"})
_REQUIRED_CONFIG = frozenset({"configuration_format_version", "evidence_classification", "release_manifest", "data_root", "target_subset", "benchmark", "discovery_sources", "discovery_policy", "universe_context", "profile_context", "profile_policy", "baseline_ranking", "benchmark_policy", "integration_policy", "integration_context", "release_policy", "expected_context_identity", "limitations"})
_SELF_REFERENTIAL_ARTIFACTS = ("reproducibility_summary.json", "output_checksums.tsv", "release_closure_manifest.json")
_TOP_LEVEL_SCIENTIFIC_ARTIFACTS = ("release_preflight.json", "stage_manifest_index.json", "artifact_compatibility.json", "release_criteria.tsv", "release_readiness.json", "activation_readiness_summary.json", "input_checksums.tsv", "limitations.tsv", "human_release_actions.json", "release_report.md")


class ReleaseClosureError(ValueError):
    """Sanitized terminal error; callers must not serialize tracebacks."""


def validate_release_state(value: str) -> str:
    if value not in RELEASE_STATES:
        raise ReleaseClosureError("unknown release state")
    return value


def validate_evidence_classification(value: str) -> str:
    if value not in EVIDENCE_CLASSIFICATIONS:
        raise ReleaseClosureError("unknown evidence classification")
    return value


def _safe_nested(value: Any) -> bool:
    """Use the canonical DepMap validator for keys and scalar disclosures."""
    return not _forbidden_nested(value)


def _path(value: str, base: Path) -> Path:
    if not isinstance(value, str) or not value or urlparse(value).scheme:
        raise ReleaseClosureError("release configuration requires local file references")
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    resolved = (base / path).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError as error:
        raise ReleaseClosureError("relative release configuration reference escapes its directory") from error
    return resolved


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseClosureError("configured JSON input could not be read") from error
    if not isinstance(value, dict):
        raise ReleaseClosureError("configured JSON input must be an object")
    return value


@dataclass(frozen=True)
class V050ReleaseRunConfiguration:
    configuration_format_version: str
    evidence_classification: str
    references: Mapping[str, Path]
    expected_context_identity: str
    limitations: tuple[str, ...]

    @property
    def configuration_id(self) -> str:
        # Paths are operational only. Bytes and declared evidence classification
        # are scientific identity inputs.
        files = {key: _sha(path) for key, path in sorted(self.references.items()) if path.is_file()}
        return _identity("v050rc", {"configuration_format_version": self.configuration_format_version,
            "evidence_classification": self.evidence_classification, "input_checksums": files,
            "expected_context_identity": self.expected_context_identity, "limitations": list(self.limitations)})

    @classmethod
    def from_file(cls, path: Path | str) -> "V050ReleaseRunConfiguration":
        config_path = Path(path).resolve(); data = _json(config_path)
        if set(data) != _REQUIRED_CONFIG:
            raise ReleaseClosureError("unknown or missing release configuration fields")
        if not _safe_nested(data):
            raise ReleaseClosureError("release configuration contains controlled credential or hidden-reasoning fields")
        if data["configuration_format_version"] != FORMAT_VERSION:
            raise ReleaseClosureError("unsupported release configuration format version")
        validate_evidence_classification(data["evidence_classification"])
        if not isinstance(data["expected_context_identity"], str) or not data["expected_context_identity"]:
            raise ReleaseClosureError("expected context identity is required")
        if not isinstance(data["limitations"], list) or not all(isinstance(x, str) and x for x in data["limitations"]):
            raise ReleaseClosureError("limitations must be explicit non-empty strings")
        refs = {key: _path(str(data[key]), config_path.parent) for key in _REQUIRED_CONFIG - {"configuration_format_version", "evidence_classification", "expected_context_identity", "limitations"}}
        return cls(FORMAT_VERSION, data["evidence_classification"], refs, data["expected_context_identity"], tuple(sorted(set(data["limitations"]))))


@dataclass(frozen=True)
class V050ReleaseClosurePolicy:
    policy_format_version: str
    allowed_evidence_classifications: tuple[str, ...]
    required_pipeline_stages: tuple[str, ...]
    minimum_benchmark_count: int
    minimum_discovery_count: int
    minimum_benchmark_coverage: float
    minimum_holdout_coverage: float
    maximum_unresolved_fraction: float
    reproducibility_required: bool
    baseline_preservation_required: bool
    release_ready_states: tuple[str, ...]
    human_review_required: bool
    candidate_activation_separate: bool
    limitations: tuple[str, ...]

    @property
    def policy_id(self) -> str:
        return _identity("v050rp", self.to_dict())
    def to_dict(self) -> dict[str, Any]:
        return {"policy_format_version": self.policy_format_version, "allowed_evidence_classifications": list(self.allowed_evidence_classifications), "required_pipeline_stages": list(self.required_pipeline_stages), "minimum_benchmark_count": self.minimum_benchmark_count, "minimum_discovery_count": self.minimum_discovery_count, "minimum_benchmark_coverage": self.minimum_benchmark_coverage, "minimum_holdout_coverage": self.minimum_holdout_coverage, "maximum_unresolved_fraction": self.maximum_unresolved_fraction, "reproducibility_required": self.reproducibility_required, "baseline_preservation_required": self.baseline_preservation_required, "release_ready_states": list(self.release_ready_states), "human_review_required": self.human_review_required, "candidate_activation_separate": self.candidate_activation_separate, "limitations": list(self.limitations)}
    @classmethod
    def from_file(cls, path: Path) -> "V050ReleaseClosurePolicy":
        data = _json(path); required = set(cls.__dataclass_fields__)
        if set(data) != required or not _safe_nested(data): raise ReleaseClosureError("unknown, missing, or unsafe release policy fields")
        try: policy = cls(**{key: tuple(sorted(data[key])) if key in {"allowed_evidence_classifications", "required_pipeline_stages", "release_ready_states", "limitations"} else data[key] for key in required})
        except (TypeError, ValueError) as error: raise ReleaseClosureError("invalid release policy") from error
        if policy.policy_format_version != FORMAT_VERSION or not set(policy.allowed_evidence_classifications).issubset(EVIDENCE_CLASSIFICATIONS) or not policy.allowed_evidence_classifications: raise ReleaseClosureError("invalid release policy classification")
        if not set(policy.release_ready_states).issubset(RELEASE_STATES) or not all(isinstance(getattr(policy, k), (int, float)) and not isinstance(getattr(policy, k), bool) for k in ("minimum_benchmark_count", "minimum_discovery_count", "minimum_benchmark_coverage", "minimum_holdout_coverage", "maximum_unresolved_fraction")): raise ReleaseClosureError("invalid release policy thresholds")
        return policy


def _write_json(path: Path, value: Any) -> None: path.write_text(canonical_json(value) + "\n", encoding="utf-8", newline="")
def _write_tsv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fields = ["criterion_id", "description", "source_artifact", "source_field", "observed_value", "comparison_operator", "threshold", "result", "mandatory", "limitations"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t"); writer.writeheader()
        for row in sorted(rows, key=lambda x: str(x["criterion_id"])): writer.writerow({k: json.dumps(row[k], sort_keys=True) if isinstance(row[k], (list, dict)) else row[k] for k in fields})


def _criterion(identifier: str, desc: str, artifact: str, field: str, observed: Any, operator: str, threshold: Any, mandatory: bool = True) -> dict[str, Any]:
    if observed is None: result = "unavailable"
    elif operator == ">=": result = "pass" if observed >= threshold else "fail"
    elif operator == "<=": result = "pass" if observed <= threshold else "fail"
    elif operator == "==": result = "pass" if observed == threshold else "fail"
    else: raise ReleaseClosureError("unsupported release criterion operator")
    return {"criterion_id": identifier, "description": desc, "source_artifact": artifact, "source_field": field, "observed_value": observed, "comparison_operator": operator, "threshold": threshold, "result": result, "mandatory": mandatory, "limitations": []}


def preflight_release(config: V050ReleaseRunConfiguration, requested_classification: str) -> dict[str, Any]:
    validate_evidence_classification(requested_classification)
    failures: list[str] = []
    if requested_classification != config.evidence_classification: failures.append("command evidence classification does not match configuration")
    for name, path in config.references.items():
        if name == "data_root":
            if not path.is_dir(): failures.append("data root is absent or not a directory")
        elif not path.is_file() or not path.stat().st_size: failures.append(f"required input is absent, not regular, or empty: {name}")
    manifest = None
    if not failures:
        try: manifest = DepMapReleaseManifest.from_dict(_json(config.references["release_manifest"]))
        except (ValueError, KeyError, TypeError, ReleaseClosureError): failures.append("release manifest is invalid")
    if manifest is not None:
        try:
            layout = DepMapLocalLayoutRequest(LOCAL_LAYOUT_REQUEST_FORMAT_VERSION, config.references["data_root"], manifest.release_identifier, config.references["data_root"], "read_only", "release_closure")
            validation = validate_local_release(manifest, layout, source_root=config.references["data_root"])
            if not validation.is_valid:
                failures.append("release manifest local-file validation failed")
        except (ValueError, KeyError, TypeError, OSError):
            failures.append("release manifest local-file validation failed")
    fixture_markers = ""
    if manifest is not None:
        fixture_markers = " ".join([manifest.release_identifier, manifest.source_name, *manifest.release_limitations]).casefold()
        if config.evidence_classification != "synthetic_fixture" and ("fixture" in fixture_markers or "synthetic" in fixture_markers): failures.append("known fixture release identity cannot be claimed as real evidence")
        if config.evidence_classification == "synthetic_fixture" and "fixture" not in fixture_markers and "synthetic" not in fixture_markers: failures.append("synthetic evidence classification requires fixture-identifiable manifest")
    return {"preflight_format_version": FORMAT_VERSION, "configuration_id": config.configuration_id, "evidence_classification": config.evidence_classification, "status": "passed" if not failures else "failed", "failures": sorted(failures), "release_manifest_id": None if manifest is None else manifest.manifest_id, "release_identifier": None if manifest is None else manifest.release_identifier, "input_checksums": {key: _sha(path) for key, path in sorted(config.references.items()) if path.is_file()}}


def _targets(path: Path) -> list[DepMapTargetRequest]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows: raise ReleaseClosureError("target subset is empty")
    return [DepMapTargetRequest(row.get("requested_identifier", ""), row.get("requested_identifier_type", "")) for row in rows]


def _release_state_before_reproducibility(policy: V050ReleaseClosurePolicy, classification: str, criteria: list[dict[str, Any]], integration: Mapping[str, Any]) -> str:
    """Return the module decision without treating candidate activation as release approval."""
    if classification == "synthetic_fixture":
        return "blocked_fixture_evidence"
    if classification not in policy.allowed_evidence_classifications:
        return "explicitly_rejected"
    # Candidate-policy outcomes remain separate from module readiness, but an
    # Issue 506 incompatibility means this closure did not operate on a
    # compatible chain of scientific artifacts and must fail closed.
    if (integration.get("decision_state") == "blocked_incompatible_inputs" or
            any(c["criterion_id"] == "integration_artifact_compatibility" and c["mandatory"] and c["result"] != "pass" for c in criteria)):
        return "blocked_incompatible_artifacts"
    if any(c["criterion_id"] in {"benchmark_count", "discovery_count", "unresolved_fraction"} and c["mandatory"] and c["result"] != "pass" for c in criteria):
        return "blocked_incomplete_universe"
    if any(c["mandatory"] and c["result"] != "pass" for c in criteria):
        return "blocked_benchmark_failure"
    # Candidate activation is intentionally separate.  A blocked candidate can
    # still leave a reproducible module ready for research-preview review.
    if integration.get("decision_state") == "eligible_for_human_activation" and "ready_optional_candidate_human_review" in policy.release_ready_states:
        return "ready_optional_candidate_human_review"
    if "ready_research_preview_human_review" in policy.release_ready_states:
        return "ready_research_preview_human_review"
    return "explicitly_rejected"


def run_release_closure(config: V050ReleaseRunConfiguration, requested_classification: str, output_dir: Path | str, *, _skip_reproducibility_check: bool = False) -> dict[str, Any]:
    output = Path(output_dir).resolve(); output.mkdir(parents=True, exist_ok=True)
    preflight = preflight_release(config, requested_classification); _write_json(output / "release_preflight.json", preflight)
    policy = V050ReleaseClosurePolicy.from_file(config.references["release_policy"])
    if preflight["status"] != "passed":
        state = "blocked_fixture_evidence" if config.evidence_classification == "synthetic_fixture" else "blocked_missing_real_data" if any("absent" in x for x in preflight["failures"]) else "blocked_invalid_real_data"
        return _finalize(output, config, policy, state, [], {}, {"status": "not_run", "human_review_required": True}, preflight)
    try:
        manifest = DepMapReleaseManifest.from_dict(_json(config.references["release_manifest"]))
        targets = _targets(config.references["target_subset"])
        full_dir, subset_dir = output / "ingestion_full", output / "ingestion_subset"
        ingest_local_release(DepMapIngestionRequest(INGESTION_REQUEST_FORMAT_VERSION, manifest, "full_matrix", config.references["data_root"], full_dir))
        ingest_local_release(DepMapIngestionRequest(INGESTION_REQUEST_FORMAT_VERSION, manifest, "target_subset", config.references["data_root"], subset_dir, target_universe=targets))
        universe_context = _json(config.references["universe_context"])
        if universe_context.get("context_identity") != config.expected_context_identity or universe_context.get("release_manifest_id") != manifest.manifest_id: raise ReleaseClosureError("universe context identities are incompatible")
        freeze_universes(config.references["benchmark"], config.references["discovery_sources"], config.references["discovery_policy"], full_dir / "gene_index.tsv", universe_context, output / "universes")
        profile_context = DepMapModelContextDefinition.from_dict(_json(config.references["profile_context"])); profile_policy = FunctionalDependencyProfilePolicy.from_dict(_json(config.references["profile_policy"]))
        profiles, assignments = build_dependency_profiles(subset_dir, profile_context, profile_policy); write_dependency_profile_artifacts(output / "profiles", profiles, assignments)
        benchmark_policy = DependencyBenchmarkPolicy.from_dict(_json(config.references["benchmark_policy"]))
        baseline_bytes = config.references["baseline_ranking"].read_bytes(); baseline_rows, baseline_id, baseline_fp = load_baseline_ranking(config.references["baseline_ranking"])
        evaluation = evaluate_dependency_benchmark(output / "universes", output / "profiles", config.references["baseline_ranking"], benchmark_policy); write_dependency_benchmark_artifacts(output / "benchmark", evaluation, benchmark_policy)
        if baseline_bytes != config.references["baseline_ranking"].read_bytes(): raise ReleaseClosureError("baseline input was modified")
        integration_context = _json(config.references["integration_context"])
        if not _safe_nested(integration_context):
            raise ReleaseClosureError("integration context contains controlled credential or hidden-reasoning fields")
        # Mandatory Issue 506 compatibility anchors for the real-release route.
        integration_context.update({"context_identity": config.expected_context_identity, "benchmark_context_identity": config.expected_context_identity, "freeze_id": json.loads((output / "universes/universe_freeze_manifest.json").read_text())["freeze_id"], "dependency_profile_run_id": profiles.run_id, "benchmark_policy_id": benchmark_policy.policy_id})
        integration_policy = DependencyIntegrationPolicy.from_dict(_json(config.references["integration_policy"]))
        issue506_scope = "synthetic_fixture" if config.evidence_classification == "synthetic_fixture" else "local_real_data"
        integration = build_dependency_integration(output / "benchmark", config.references["baseline_ranking"], integration_policy, integration_context, issue506_scope); write_dependency_integration_artifacts(output / "integration", integration)
        metrics = _collect_metrics(output, baseline_id, baseline_fp, profiles.run_id, integration)
        criteria = _criteria(policy, metrics)
        state = _release_state_before_reproducibility(policy, config.evidence_classification, criteria, integration["decision"])
        reproducibility: Mapping[str, Any] | None = None
        if state.startswith("ready") and policy.reproducibility_required and not _skip_reproducibility_check:
            # The comparison is a second, direct API execution in an isolated
            # temporary directory.  No external process, download, or operational
            # path enters the scientific identity.
            # Finalize once before comparison so the primary and replica both
            # contain every non-self-referential top-level scientific artifact.
            _finalize(output, config, policy, state, criteria, metrics, integration["decision"], preflight)
            with tempfile.TemporaryDirectory(prefix="targetintel-v050-repro-") as temporary:
                replica = run_release_closure(config, requested_classification, Path(temporary), _skip_reproducibility_check=True)
                reproducibility = compare_release_runs(output, temporary)
                if not replica["successful_closure"]:
                    reproducibility = {**reproducibility, "differing_artifacts": sorted(set(reproducibility["differing_artifacts"] + ["replica_terminal_state"])), "result": "nonreproducible"}
            if reproducibility["result"] != "reproducible":
                state = "blocked_nonreproducible"
        return _finalize(output, config, policy, state, criteria, metrics, integration["decision"], preflight, reproducibility)
    except (ValueError, OSError, ReleaseClosureError) as error:
        # A sanitized blocked record, never a raw traceback or false success.
        state = "blocked_fixture_evidence" if config.evidence_classification == "synthetic_fixture" else "blocked_invalid_real_data"
        return _finalize(output, config, policy, state, [], {"failure": str(error), "failure_category": "pipeline_execution_failure"}, {"status": "not_run", "human_review_required": True}, preflight)


def _collect_metrics(output: Path, baseline_id: str, baseline_fp: str, profile_run_id: str, integration: Mapping[str, Any]) -> dict[str, Any]:
    benchmark = _json(output / "benchmark/benchmark_coverage.json"); universe = _json(output / "universes/universe_overlap.json")
    unresolved = max(0, universe["counts"].get("unresolved", 0)); discovery = sum(1 for _ in csv.DictReader((output / "universes/discovery_universe.tsv").open(), delimiter="\t")); background = sum(1 for _ in csv.DictReader((output / "universes/background_universe.tsv").open(), delimiter="\t"));
    return {"benchmark_count": benchmark.get("total_benchmark_targets"), "development_count": benchmark.get("development_benchmark_targets"), "holdout_count": benchmark.get("holdout_benchmark_targets"), "discovery_count": discovery, "background_count": background, "benchmark_coverage": benchmark.get("profiled_target_count", 0) / benchmark.get("total_benchmark_targets", 1), "holdout_coverage": next((x.get("observed") for x in _json(output / "benchmark/integration_evidence.json").get("criteria", []) if x.get("criterion") == "minimum_holdout_coverage"), None), "unresolved_count": unresolved, "unresolved_fraction": unresolved / max(discovery, 1), "baseline_ranking_id": baseline_id, "baseline_fingerprint": baseline_fp, "profile_run_id": profile_run_id, "integration_state": integration.get("decision_state"), "integration_artifacts_compatible": integration.get("compatibility", {}).get("compatible"), "baseline_preserved": integration.get("criteria", [])[-1].get("result") == "pass" if integration.get("criteria") else False}


def _criteria(policy: V050ReleaseClosurePolicy, m: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_criterion("benchmark_count", "Actual benchmark count meets the immutable minimum.", "benchmark_coverage.json", "total_benchmark_targets", m.get("benchmark_count"), ">=", policy.minimum_benchmark_count), _criterion("discovery_count", "Discovery universe count meets the immutable minimum.", "discovery_universe.tsv", "row_count", m.get("discovery_count"), ">=", policy.minimum_discovery_count), _criterion("benchmark_coverage", "Benchmark profile coverage meets the immutable minimum.", "benchmark_coverage.json", "profiled/total", m.get("benchmark_coverage"), ">=", policy.minimum_benchmark_coverage), _criterion("holdout_coverage", "Holdout coverage meets the immutable minimum.", "integration_evidence.json", "minimum_holdout_coverage", m.get("holdout_coverage"), ">=", policy.minimum_holdout_coverage), _criterion("unresolved_fraction", "Unresolved target fraction remains within policy.", "universe_overlap.json", "unresolved/discovery", m.get("unresolved_fraction"), "<=", policy.maximum_unresolved_fraction), _criterion("integration_artifact_compatibility", "Issue 506 accepted the same intermediate artifact identities and overlay recipe.", "input_compatibility.json", "compatible", m.get("integration_artifacts_compatible"), "==", True), _criterion("baseline_preservation", "Baseline bytes, scores, and ranks remain unchanged.", "baseline_preservation.json", "all preservation checks", m.get("baseline_preserved"), "==", True)]


def compare_release_runs(first: Path | str, second: Path | str) -> dict[str, Any]:
    """Compare scientific closure artifacts while excluding operational location."""
    left, right = Path(first), Path(second)
    scientific_roots = ("ingestion_full", "ingestion_subset", "universes", "profiles", "benchmark", "integration")
    names = list(_TOP_LEVEL_SCIENTIFIC_ARTIFACTS)
    names.extend(sorted({str(path.relative_to(left)) for root in scientific_roots for path in (left / root).rglob("*") if path.is_file()} | {str(path.relative_to(right)) for root in scientific_roots for path in (right / root).rglob("*") if path.is_file()}))
    differing = []
    for name in names:
        a, b = left / name, right / name
        if not a.is_file() or not b.is_file() or a.read_bytes() != b.read_bytes(): differing.append(name)
    configuration_id = None
    if (left / "release_closure_manifest.json").is_file(): configuration_id = _json(left / "release_closure_manifest.json").get("configuration_id")
    inventories = {"first": _output_inventory_is_valid(left), "second": _output_inventory_is_valid(right)}
    manifest_ids = {"first": _closure_identity(left), "second": _closure_identity(right)}
    return {"reproducibility_format_version": FORMAT_VERSION, "configuration_id": configuration_id, "compared_artifacts": list(names), "differing_artifacts": differing, "excluded_artifacts": list(_SELF_REFERENTIAL_ARTIFACTS), "excluded_artifact_invariants": {"output_checksum_inventory_valid": inventories, "closure_scientific_identity": manifest_ids}, "excluded_operational_fields": ["output_path", "timestamp", "hostname", "username", "runtime_duration"], "result": "reproducible" if not differing and all(inventories.values()) and manifest_ids["first"] == manifest_ids["second"] else "nonreproducible"}


def _output_inventory_is_valid(directory: Path) -> bool:
    table = directory / "output_checksums.tsv"
    if not table.is_file():
        return False
    try:
        rows = list(csv.DictReader(table.open(encoding="utf-8", newline=""), delimiter="\t"))
        return all(set(row) == {"name", "sha256"} and (directory / row["name"]).is_file() and _sha(directory / row["name"]) == row["sha256"] for row in rows)
    except (OSError, KeyError, TypeError):
        return False


def _closure_identity(directory: Path) -> str | None:
    try:
        closure = _json(directory / "release_closure_manifest.json")
        return _identity("v050closure", {key: closure.get(key) for key in ("configuration_id", "policy_id", "evidence_classification")})
    except ReleaseClosureError:
        return None


def _finalize(output: Path, config: V050ReleaseRunConfiguration, policy: V050ReleaseClosurePolicy, state: str, criteria: list[dict[str, Any]], metrics: Mapping[str, Any], activation: Mapping[str, Any], preflight: Mapping[str, Any], reproducibility: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_release_state(state); stage_names = ["ingestion_full", "ingestion_subset", "universes", "profiles", "benchmark", "integration"]
    stages = [{"stage": name, "manifest_present": any((output / name).glob("*manifest*.json")), "status": "completed" if (output / name).is_dir() else "not_completed"} for name in stage_names]
    _write_json(output / "stage_manifest_index.json", {"configuration_id": config.configuration_id, "stages": stages})
    _write_json(output / "artifact_compatibility.json", {"compatible": all(x["status"] == "completed" for x in stages) if state.startswith("ready") else False, "expected_context_identity": config.expected_context_identity, "metrics": dict(metrics)})
    _write_tsv(output / "release_criteria.tsv", criteria)
    input_rows = [{"name": k, "sha256": v} for k, v in sorted(preflight.get("input_checksums", {}).items())]
    (output / "input_checksums.tsv").write_text("name\tsha256\n" + "".join(f"{r['name']}\t{r['sha256']}\n" for r in input_rows), encoding="utf-8", newline="")
    readiness = {"release_readiness_format_version": FORMAT_VERSION, "release_state": state, "human_review_required": True, "production_activation_enabled": False, "configuration_id": config.configuration_id, "policy_id": policy.policy_id, "criteria": criteria, "limitations": list(config.limitations)}
    _write_json(output / "release_readiness.json", readiness)
    _write_json(output / "activation_readiness_summary.json", {"module_release_state": state, "integration_state": activation.get("decision_state", activation.get("status")), "candidate_activation_readiness": "blocked" if str(activation.get("decision_state", "")).startswith("blocked") or state == "blocked_fixture_evidence" else "eligible_for_human_review", "human_review_required": True, "approved_authorization_emitted": False})
    (output / "limitations.tsv").write_text("limitation\n" + "".join(x + "\n" for x in sorted(set(config.limitations + ("No automatic tag, version change, or production activation.",)))), encoding="utf-8", newline="")
    _write_json(output / "human_release_actions.json", {"human_review_required": True, "automatic_tag_created": False, "actions": ["Inspect real-data source licensing and provenance.", "Inspect benchmark and holdout behaviour.", "Inspect unresolved targets and reproducibility results.", "Decide module research-preview release separately from candidate activation.", "Manually create any release tag and later update public release metadata."]})
    (output / "release_report.md").write_text("# v0.5.0 release closure\n\n- Module release state: `" + state + "`\n- Candidate activation remains a separate human decision.\n- No production activation, tag, or version change is performed.\n", encoding="utf-8", newline="")
    # The closure manifest, checksum table, and reproducibility summary are
    # intentionally excluded to avoid a self-referential checksum cycle.  All
    # other release-decision artifacts must exist before this inventory is made.
    outputs = [{"name": str(p.relative_to(output)), "sha256": _sha(p)} for p in sorted(output.rglob("*")) if p.is_file() and p.name not in {"output_checksums.tsv", "release_closure_manifest.json", "reproducibility_summary.json"}]
    (output / "output_checksums.tsv").write_text("name\tsha256\n" + "".join(f"{r['name']}\t{r['sha256']}\n" for r in outputs), encoding="utf-8", newline="")
    reproducibility = dict(reproducibility or {"reproducibility_format_version": FORMAT_VERSION, "configuration_id": config.configuration_id, "differing_artifacts": [], "excluded_artifacts": list(_SELF_REFERENTIAL_ARTIFACTS), "excluded_artifact_invariants": {}, "result": "not_compared"})
    reproducibility.update({"scientific_artifact_checksums": outputs, "excluded_operational_fields": ["output_path", "timestamp", "hostname", "username", "runtime_duration"]})
    _write_json(output / "reproducibility_summary.json", reproducibility)
    closure = {"release_closure_format_version": FORMAT_VERSION, "configuration_id": config.configuration_id, "policy_id": policy.policy_id, "evidence_classification": config.evidence_classification, "terminal_state": state, "successful_closure": state.startswith("ready"), "human_review_required": True, "production_activation_enabled": False}
    _write_json(output / "release_closure_manifest.json", closure)
    return closure
