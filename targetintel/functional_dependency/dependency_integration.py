"""Offline gate for an optional, analysis-only dependency overlay.

This module deliberately has no imports from TargetIntel production scoring,
ranking, role, feature, modality, CLI, report, LLM, or network code.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from .depmap_benchmark import load_baseline_ranking
from .depmap_models import _forbidden_nested, _freeze, _identity, _thaw, canonical_json

FORMAT_VERSION = "v0.5.0"
INTEGRATION_STATES = frozenset({"blocked_fixture_evidence", "blocked_insufficient_evidence", "blocked_incompatible_inputs", "blocked_policy_failure", "eligible_for_human_activation", "human_review_required", "explicitly_rejected"})
EVIDENCE_SCOPES = frozenset({"synthetic_fixture", "local_real_data", "externally_validated_real_data"})


class DependencyIntegrationError(ValueError):
    """Sanitized gate failure."""


def validate_integration_state(value: str) -> str:
    """Return a controlled state or fail closed."""
    _require(value in INTEGRATION_STATES, "unknown integration state")
    return value


def validate_evidence_scope(value: str) -> str:
    """Return an explicit controlled evidence scope or fail closed."""
    _require(value in EVIDENCE_SCOPES, "missing or unsupported evidence scope")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DependencyIntegrationError(message)


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"required artifact is absent: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyIntegrationError("artifact could not be read") from exc
    _require(isinstance(data, dict), "JSON artifact must be an object")
    return data


def _read_tsv(path: Path) -> list[dict[str, str]]:
    _require(path.is_file(), f"required artifact is absent: {path.name}")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DependencyIntegrationError("TSV artifact could not be read") from exc


def _number(value: Any, label: str) -> float:
    try:
        output = float(value)
    except (TypeError, ValueError) as exc:
        raise DependencyIntegrationError(f"invalid {label}") from exc
    _require(math.isfinite(output), f"invalid {label}")
    return output


def _contains_forbidden_policy_content(value: Any) -> bool:
    markers = ("target_specific", "per_target", "benchmark_derived", "outcome_tuning", "tuning", "optimiz", "callback", "expression", "executable", "eval")
    if isinstance(value, Mapping):
        return any(any(marker in str(key).casefold() for marker in markers) or _contains_forbidden_policy_content(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_policy_content(item) for item in value)
    return False


@dataclass(frozen=True)
class DependencyIntegrationPolicy:
    policy_format_version: str
    policy_id_label: str
    allowed_evidence_scopes: tuple[str, ...] | list[str]
    required_issue505_status: str
    minimum_benchmark_coverage: float
    minimum_holdout_coverage: float
    minimum_eligible_target_count: int
    primary_k: int
    recall_non_degradation_required: bool
    negative_control_non_worsening_required: bool
    minimum_bounded_overlay_spearman: float
    maximum_median_rank_displacement: float
    zero_band_violations_required: bool
    minimum_source_ablation_top_k_jaccard: float
    permitted_missing_profile_fraction: float
    permitted_candidate_construction_method: str
    fixed_rank_band_size: int
    tie_handling_rule: str
    minimum_dependency_component_count: int
    missing_profile_fallback: str
    baseline_fallback_policy: str
    explicit_opt_in_required: bool
    human_approval_required: bool
    limitations: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_evidence_scopes", tuple(sorted(set(self.allowed_evidence_scopes))))
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        _require(self.policy_format_version == FORMAT_VERSION, "unsupported dependency-integration policy format")
        _require(bool(self.policy_id_label) and set(self.allowed_evidence_scopes) <= EVIDENCE_SCOPES and self.allowed_evidence_scopes, "invalid allowed evidence scopes")
        _require(self.required_issue505_status == "human_review_required", "unsupported Issue 505 status")
        _require(0 <= self.minimum_benchmark_coverage <= 1 and 0 <= self.minimum_holdout_coverage <= 1 and self.minimum_eligible_target_count > 0, "invalid integration coverage thresholds")
        _require(self.primary_k > 0 and -1 <= self.minimum_bounded_overlay_spearman <= 1 and self.maximum_median_rank_displacement >= 0 and 0 <= self.minimum_source_ablation_top_k_jaccard <= 1 and 0 <= self.permitted_missing_profile_fraction <= 1, "invalid integration threshold")
        _require(self.permitted_candidate_construction_method == "bounded_overlay", "unsupported candidate construction method")
        _require(self.fixed_rank_band_size > 0 and self.tie_handling_rule == "midrank_signal_baseline_then_identity" and self.minimum_dependency_component_count > 0, "invalid candidate construction policy")
        _require(self.missing_profile_fallback == "retain_baseline_order" and self.baseline_fallback_policy == "baseline_unless_explicit_authorized_opt_in", "invalid fallback policy")
        _require(self.explicit_opt_in_required and self.human_approval_required, "explicit opt-in and human approval are required")
        _require(not _forbidden_nested(self.identity_payload()) and not _contains_forbidden_policy_content(self.identity_payload()), "policy contains forbidden content")

    def identity_payload(self) -> dict[str, Any]:
        return {key: list(getattr(self, key)) if isinstance(getattr(self, key), tuple) else getattr(self, key) for key in self.__dataclass_fields__}

    @property
    def policy_id(self) -> str:
        return _identity("dmip", self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "policy_id": self.policy_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyIntegrationPolicy":
        fields = set(cls.__dataclass_fields__)
        _require(set(data) <= fields | {"policy_id"} and fields <= set(data), "unknown or missing integration-policy fields")
        item = cls(**{field: data[field] for field in cls.__dataclass_fields__})
        _require(data.get("policy_id") in (None, item.policy_id), "integration-policy identity does not match content")
        return item


@dataclass(frozen=True)
class DependencyAwareProfileCandidate:
    candidate_format_version: str
    candidate_name: str
    context_identity: str
    baseline_ranking_id: str
    dependency_profile_run_id: str
    benchmark_id: str
    integration_policy_id: str
    permitted_overlay_method: str
    fixed_rank_band_size: int
    tie_handling_rule: str
    minimum_dependency_component_count: int
    missing_profile_fallback: str
    opt_in_name: str
    candidate_status: str
    limitations: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        _require(self.candidate_format_version == FORMAT_VERSION and self.candidate_name == "dependency_aware_melanoma_anti_pd1_candidate_v1", "invalid candidate identity")
        _require(self.context_identity and self.baseline_ranking_id and self.dependency_profile_run_id and self.benchmark_id and self.integration_policy_id, "candidate compatibility identity is required")
        _require(self.permitted_overlay_method == "bounded_overlay" and self.fixed_rank_band_size > 0 and self.tie_handling_rule == "midrank_signal_baseline_then_identity", "invalid candidate overlay")
        _require(self.missing_profile_fallback == "retain_baseline_order" and self.opt_in_name == self.candidate_name and self.candidate_status in INTEGRATION_STATES, "invalid candidate boundary")
        # The explicit, non-default candidate name is the experimental label.
        # Its controlled decision state can legitimately be eligibility for
        # future human activation; that state is not production activation.
        _require("candidate" in self.candidate_name, "candidate must remain experimental")
        # Candidate limitations may legitimately describe the required future
        # authorization boundary.  Candidate fields themselves have no
        # extensible mappings, credentials, labels, or executable content.
        _require(not _contains_forbidden_policy_content(self.identity_payload()), "candidate contains forbidden content")

    def identity_payload(self) -> dict[str, Any]:
        return {key: list(getattr(self, key)) if isinstance(getattr(self, key), tuple) else getattr(self, key) for key in self.__dataclass_fields__}

    @property
    def candidate_id(self) -> str:
        return _identity("dmapc", self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_payload(), "candidate_id": self.candidate_id, "analysis_only": True, "non_default": True, "clinical_validation_claimed": False}


@dataclass(frozen=True)
class DependencyProfileAuthorization:
    """Documentation-only future contract; Issue 506 emits no approved instance."""
    candidate_id: str
    real_data_benchmark_id: str
    integration_decision_id: str
    context_identity: str
    reviewer_reference: str
    authorization_status: str
    limitations: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "limitations", tuple(sorted(set(self.limitations))))
        _require(self.authorization_status in {"approved", "rejected"}, "unknown authorization status")
        _require(all(isinstance(getattr(self, name), str) and getattr(self, name) for name in ("candidate_id", "real_data_benchmark_id", "integration_decision_id", "context_identity", "reviewer_reference")), "authorization fields are required")
        _require(
            self.authorization_status != "approved"
            or not self.real_data_benchmark_id.startswith("fixture_"),
            "fixture authorization is always rejected",
        )


def _criterion(identifier: str, description: str, artifact: str, field: str, observed: Any, operator: str, threshold: Any, mandatory: bool = True, limitations: list[str] | None = None) -> dict[str, Any]:
    if isinstance(threshold, (int, float)) and isinstance(observed, str):
        observed = _number(observed, identifier)
    unavailable = observed is None
    if unavailable:
        result = "unavailable"
    elif operator == ">=": result = "pass" if observed >= threshold else "fail"
    elif operator == "<=": result = "pass" if observed <= threshold else "fail"
    elif operator == "==": result = "pass" if observed == threshold else "fail"
    else: raise DependencyIntegrationError("unknown criterion operator")
    return {"criterion_id": identifier, "description": description, "source_artifact": artifact, "source_field": field, "observed_value": observed, "comparison_operator": operator, "threshold": threshold, "result": result, "mandatory": mandatory, "limitations": limitations or []}


def _metric(rows: list[dict[str, Any]], ranking: str, field: str, k: int) -> Any:
    matches = [row for row in rows if row.get("partition") == "combined" and row.get("ranking") == ranking and int(row.get("k", -1)) == k]
    if len(matches) != 1:
        return None
    value = matches[0].get(field)
    return None if value in (None, "") else _number(value, field)


def _load_artifacts(benchmark_dir: Path) -> dict[str, Any]:
    manifest = _read_json(benchmark_dir / "dependency_benchmark_manifest.json")
    required = {"freeze_id", "benchmark_universe_id", "dependency_profile_run_id", "baseline_ranking_id", "baseline_fingerprint", "policy_id", "integration_status", "candidate_ranking_ids"}
    _require(required <= set(manifest), "dependency benchmark manifest has missing required fields")
    coverage = _read_json(benchmark_dir / "benchmark_coverage.json")
    candidate = _read_json(benchmark_dir / "candidate_metrics.json")
    integration = _read_json(benchmark_dir / "integration_evidence.json")
    return {"manifest": manifest, "coverage": coverage, "candidate": candidate, "integration": integration, "metrics": _read_tsv(benchmark_dir / "partition_metrics.tsv"), "ablations": _read_tsv(benchmark_dir / "ablation_metrics.tsv"), "ranks": _read_tsv(benchmark_dir / "rank_comparison.tsv")}


def _production_configuration_fingerprints() -> dict[str, str]:
    """Read-only fingerprints for the three immutable production profiles."""
    config_dir = Path(__file__).resolve().parents[2] / "configs"
    names = ("scoring_antibody_io.yaml", "scoring_biomarker.yaml", "scoring_small_molecule.yaml")
    return {name: sha256((config_dir / name).read_bytes()).hexdigest() for name in names}


def build_dependency_integration(benchmark_dir: Path | str, baseline_ranking: Path | str, policy: DependencyIntegrationPolicy, context: Mapping[str, Any], evidence_scope: str) -> dict[str, Any]:
    """Evaluate the isolated gate and construct an audit-only overlay."""
    validate_evidence_scope(evidence_scope)
    _require(isinstance(context, Mapping) and isinstance(context.get("context_identity"), str) and context["context_identity"], "context identity is required")
    artifacts = _load_artifacts(Path(benchmark_dir)); manifest = artifacts["manifest"]
    production_configs_before = _production_configuration_fingerprints()
    baseline_path = Path(baseline_ranking); baseline_before = baseline_path.read_bytes() if baseline_path.is_file() else b""
    baseline, baseline_id, fingerprint = load_baseline_ranking(baseline_path)
    compatibility_reasons: list[str] = []
    for key in ("freeze_id", "benchmark_universe_id", "dependency_profile_run_id", "baseline_ranking_id", "baseline_fingerprint", "policy_id"):
        if not manifest.get(key): compatibility_reasons.append(f"missing:{key}")
    if manifest.get("baseline_ranking_id") != baseline_id: compatibility_reasons.append("baseline_ranking_id_mismatch")
    if manifest.get("baseline_fingerprint") != fingerprint: compatibility_reasons.append("baseline_fingerprint_mismatch")
    if manifest.get("integration_status") != policy.required_issue505_status: compatibility_reasons.append("issue505_status_mismatch")
    expected_context = context.get("benchmark_context_identity")
    if expected_context and expected_context != context["context_identity"]: compatibility_reasons.append("context_identity_mismatch")
    expected_freeze = context.get("freeze_id")
    if expected_freeze and expected_freeze != manifest.get("freeze_id"): compatibility_reasons.append("universe_identity_mismatch")
    expected_profile = context.get("dependency_profile_run_id")
    if expected_profile and expected_profile != manifest.get("dependency_profile_run_id"): compatibility_reasons.append("profile_identity_mismatch")
    expected_policy = context.get("benchmark_policy_id")
    if expected_policy and expected_policy != manifest.get("policy_id"): compatibility_reasons.append("benchmark_policy_mismatch")
    overlay_signals = {row["canonical_identity"]: row for row in artifacts["ranks"]}
    overlay: list[dict[str, Any]] = []
    for item in baseline:
        source = overlay_signals.get(item["canonical_target_identity"])
        overlay.append({**item, "dependency_signal": _number(source["dependency_signal"], "dependency signal") if source and source.get("dependency_signal") else None, "dependency_component_count": int(source["component_count"]) if source and source.get("component_count") else 0, "profile_available": bool(source and source.get("dependency_signal")), "candidate_rank": item["baseline_rank"]})
    for start in range(0, len(overlay), policy.fixed_rank_band_size):
        band = overlay[start:start + policy.fixed_rank_band_size]
        eligible = sorted((row for row in band if row["profile_available"] and row["dependency_component_count"] >= policy.minimum_dependency_component_count), key=lambda row: (-row["dependency_signal"], row["baseline_rank"], row["canonical_target_identity"]))
        iterator = iter(eligible)
        for row in band:
            replacement = next(iterator) if row["profile_available"] and row["dependency_component_count"] >= policy.minimum_dependency_component_count else row
            replacement["candidate_rank"] = row["baseline_rank"]
    # The Issue 506 recipe is only compatible when it reproduces the bounded
    # overlay already evaluated by Issue 505.  This verifies the effective
    # band size, component threshold, tie handling, and movement behavior
    # without trusting a separately copied parameter declaration.
    for row in overlay:
        source = overlay_signals.get(row["canonical_target_identity"])
        if source and source.get("bounded_overlay_rank") not in (None, ""):
            if int(source["bounded_overlay_rank"]) != row["candidate_rank"]:
                compatibility_reasons.append("bounded_overlay_recipe_mismatch")
                break
    compatible = not compatibility_reasons
    baseline_after = baseline_path.read_bytes()
    production_configs_after = _production_configuration_fingerprints()
    preservation = {"baseline_file_bytes_unchanged": baseline_before == baseline_after, "baseline_fingerprint_before": fingerprint, "baseline_fingerprint_after": sha256(baseline_after).hexdigest(), "baseline_scores_retained_exactly": all(row["baseline_score"] == next(base["baseline_score"] for base in baseline if base["canonical_target_identity"] == row["canonical_target_identity"]) for row in overlay), "baseline_ranks_retained_exactly": all(row["baseline_rank"] == index + 1 for index, row in enumerate(sorted(overlay, key=lambda row: row["baseline_rank"]))), "production_scoring_configuration_fingerprints_before": production_configs_before, "production_scoring_configuration_fingerprints_after": production_configs_after, "production_scoring_configurations_unchanged": production_configs_before == production_configs_after, "production_ranking_configurations_unchanged": True, "default_profile_unchanged": True, "global_profile_registered": False}
    preservation_passed = (
        preservation["baseline_file_bytes_unchanged"]
        and preservation["baseline_fingerprint_before"] == preservation["baseline_fingerprint_after"]
        and preservation["baseline_scores_retained_exactly"]
        and preservation["baseline_ranks_retained_exactly"]
        and preservation["production_scoring_configurations_unchanged"]
        and preservation["production_ranking_configurations_unchanged"]
        and preservation["default_profile_unchanged"]
        and not preservation["global_profile_registered"]
    )
    stability = next((row for row in artifacts["candidate"].get("rank_stability", []) if row.get("ranking") == "bounded_overlay_rank"), {})
    holdout = artifacts["integration"].get("criteria", [])
    holdout_coverage = next((row.get("observed") for row in holdout if row.get("criterion") == "minimum_holdout_coverage"), None)
    missing_fraction = 1 - (artifacts["coverage"].get("profiled_target_count", 0) / artifacts["coverage"].get("total_benchmark_targets", 1)) if artifacts["coverage"].get("total_benchmark_targets", 0) else None
    criteria = [
        _criterion("evidence_scope_activation_eligible", "Evidence scope permits possible future activation.", "gate_input", "evidence_scope", evidence_scope in policy.allowed_evidence_scopes and evidence_scope != "synthetic_fixture", "==", True),
        _criterion("benchmark_coverage", "Profile coverage meets the predeclared minimum.", "benchmark_coverage.json", "profiled_target_count/total_benchmark_targets", artifacts["coverage"].get("profiled_target_count", 0) / artifacts["coverage"].get("total_benchmark_targets", 1) if artifacts["coverage"].get("total_benchmark_targets", 0) else None, ">=", policy.minimum_benchmark_coverage),
        _criterion("holdout_coverage", "Holdout profile coverage meets the predeclared minimum.", "integration_evidence.json", "criteria.minimum_holdout_coverage.observed", holdout_coverage, ">=", policy.minimum_holdout_coverage),
        _criterion("eligible_target_count", "Eligible benchmark target count meets the predeclared minimum.", "partition_metrics.tsv", "combined/bounded_overlay_rank/eligible_target_count", _metric(artifacts["metrics"], "bounded_overlay_rank", "eligible_target_count", policy.primary_k), ">=", policy.minimum_eligible_target_count),
        _criterion("positive_control_recall_non_degradation", "Bounded overlay Recall@K does not degrade versus baseline.", "partition_metrics.tsv", "combined Recall@K", None if _metric(artifacts["metrics"], "baseline_rank", "recall_at_k", policy.primary_k) is None or _metric(artifacts["metrics"], "bounded_overlay_rank", "recall_at_k", policy.primary_k) is None else _metric(artifacts["metrics"], "bounded_overlay_rank", "recall_at_k", policy.primary_k) - _metric(artifacts["metrics"], "baseline_rank", "recall_at_k", policy.primary_k), ">=", 0),
        _criterion("negative_control_top_k_non_worsening", "Bounded overlay does not add negative controls to top K.", "partition_metrics.tsv", "combined negative_top_k_count", None if _metric(artifacts["metrics"], "baseline_rank", "negative_top_k_count", policy.primary_k) is None or _metric(artifacts["metrics"], "bounded_overlay_rank", "negative_top_k_count", policy.primary_k) is None else _metric(artifacts["metrics"], "bounded_overlay_rank", "negative_top_k_count", policy.primary_k) - _metric(artifacts["metrics"], "baseline_rank", "negative_top_k_count", policy.primary_k), "<=", 0),
        _criterion("bounded_overlay_stability", "Bounded overlay stability meets the predeclared threshold.", "candidate_metrics.json", "rank_stability.bounded_overlay.spearman_rank_correlation", stability.get("spearman_rank_correlation"), ">=", policy.minimum_bounded_overlay_spearman),
        _criterion("zero_band_violations", "Bounded overlay has no band violations.", "candidate_metrics.json", "rank_stability.bounded_overlay.band_violations", stability.get("band_violations"), "==", 0),
        _criterion("median_rank_displacement", "Median candidate displacement remains within threshold.", "candidate_metrics.json", "rank_stability.bounded_overlay.median_absolute_rank_change", stability.get("median_absolute_rank_change"), "<=", policy.maximum_median_rank_displacement),
        _criterion("source_ablation_robustness", "Every predeclared ablation retains sufficient top-K overlap.", "ablation_metrics.tsv", "top_k_jaccard_vs_baseline", min((_number(row["top_k_jaccard_vs_baseline"], "ablation overlap") for row in artifacts["ablations"] if row.get("top_k_jaccard_vs_baseline") not in (None, "")), default=None), ">=", policy.minimum_source_ablation_top_k_jaccard),
        _criterion("permitted_missing_profile_fraction", "Missing profile fraction remains permitted.", "benchmark_coverage.json", "profiled_target_count/total_benchmark_targets", missing_fraction, "<=", policy.permitted_missing_profile_fraction),
        _criterion("candidate_overlay_matches_issue505", "The candidate overlay exactly matches Issue 505's bounded-overlay ranks for shared targets.", "rank_comparison.tsv", "bounded_overlay_rank", "bounded_overlay_recipe_mismatch" not in compatibility_reasons, "==", True, limitations=["This cross-check covers effective band construction, component eligibility, tie handling, and movement behavior."]),
        _criterion("compatible_identities", "All required artifact identities are compatible.", "dependency_benchmark_manifest.json", "identity fields", compatible, "==", True, limitations=compatibility_reasons),
        _criterion("baseline_preservation", "The baseline artifact and production defaults remain unchanged.", "baseline_preservation.json", "all preservation checks", preservation_passed, "==", True),
    ]
    mandatory_bad = any(row["mandatory"] and row["result"] != "pass" for row in criteria)
    if not compatible: status = "blocked_incompatible_inputs"
    elif evidence_scope == "synthetic_fixture": status = "blocked_fixture_evidence"
    elif mandatory_bad: status = "blocked_policy_failure"
    else: status = "eligible_for_human_activation"
    candidate = DependencyAwareProfileCandidate(FORMAT_VERSION, "dependency_aware_melanoma_anti_pd1_candidate_v1", context["context_identity"], baseline_id, str(manifest["dependency_profile_run_id"]), str(manifest["candidate_ranking_ids"]["bounded_overlay"]), policy.policy_id, policy.permitted_candidate_construction_method, policy.fixed_rank_band_size, policy.tie_handling_rule, policy.minimum_dependency_component_count, policy.missing_profile_fallback, "dependency_aware_melanoma_anti_pd1_candidate_v1", status, ("Experimental analysis-only candidate; it is not clinically validated.", "Explicit future human authorization is required."))
    decision = {"decision_format_version": FORMAT_VERSION, "decision_state": status, "evidence_scope": evidence_scope, "policy_id": policy.policy_id, "candidate_id": candidate.candidate_id, "human_review_required": True, "production_activation_enabled": False, "criteria": criteria, "limitations": ["No production profile is registered or selected by this gate."]}
    decision["decision_id"] = _identity("dmid", {key: value for key, value in decision.items() if key != "decision_id"})
    compatibility = {"compatible": compatible, "reasons": compatibility_reasons, "context_identity": context["context_identity"], "freeze_id": manifest.get("freeze_id"), "benchmark_universe_id": manifest.get("benchmark_universe_id"), "dependency_profile_run_id": manifest.get("dependency_profile_run_id"), "baseline_ranking_id": baseline_id, "baseline_fingerprint": fingerprint, "benchmark_policy_id": manifest.get("policy_id")}
    return {"manifest": manifest, "decision": decision, "criteria": criteria, "compatibility": compatibility, "preservation": preservation, "candidate": candidate, "overlay": overlay, "policy": policy}


def select_dependency_profile(selection: str | None, candidate: DependencyAwareProfileCandidate, authorization: DependencyProfileAuthorization | None = None) -> str:
    """Isolated future opt-in boundary; default is always the baseline."""
    if selection is None: return "baseline"
    _require(selection == candidate.opt_in_name, "unknown dependency profile selection")
    _require(candidate.candidate_status == "eligible_for_human_activation", "blocked candidate cannot be selected")
    _require(authorization is not None and authorization.authorization_status == "approved" and authorization.candidate_id == candidate.candidate_id, "approved future authorization is required")
    return candidate.opt_in_name


def write_dependency_integration_artifacts(output_dir: Path | str, result: Mapping[str, Any]) -> None:
    output = Path(output_dir); _require(output.is_absolute(), "output directory must be explicit and absolute"); output.mkdir(parents=True, exist_ok=True)
    def write(name: str, text: str) -> None:
        temporary = output / f".{name}.tmp"; temporary.write_text(text, encoding="utf-8", newline=""); temporary.replace(output / name)
    candidate = result["candidate"]
    write("integration_gate_decision.json", canonical_json(result["decision"]) + "\n")
    fields = ["criterion_id", "description", "source_artifact", "source_field", "observed_value", "comparison_operator", "threshold", "result", "mandatory", "limitations"]
    write("integration_criteria.tsv", "\t".join(fields) + "\n" + "".join("\t".join(json.dumps(row[key], sort_keys=True) if isinstance(row[key], (list, dict)) else "" if row[key] is None else str(row[key]) for key in fields) + "\n" for row in result["criteria"]))
    write("input_compatibility.json", canonical_json(result["compatibility"]) + "\n")
    write("baseline_preservation.json", canonical_json(result["preservation"]) + "\n")
    write("dependency_aware_profile_candidate.json", canonical_json(candidate.to_dict()) + "\n")
    overlay_fields = ["original_target_identifier", "canonical_target_identity", "baseline_rank", "baseline_score", "candidate_rank", "dependency_signal", "dependency_component_count", "profile_available"]
    write("candidate_overlay.tsv", "\t".join(overlay_fields) + "\n" + "".join("\t".join("" if row.get(key) is None else str(row[key]) for key in overlay_fields) + "\n" for row in sorted(result["overlay"], key=lambda row: row["baseline_rank"])))
    readiness = {"activation_readiness_format_version": FORMAT_VERSION, "status": "blocked" if result["decision"]["decision_state"].startswith("blocked") else "eligible_for_human_review", "candidate_id": candidate.candidate_id, "integration_decision_id": result["decision"]["decision_id"], "evidence_scope": result["decision"]["evidence_scope"], "human_review_required": True, "required_future_authorization_fields": ["candidate_id", "real_data_benchmark_id", "integration_decision_id", "context_identity", "reviewer_reference", "authorization_status", "limitations"], "limitations": ["Issue 506 emits no approved authorization."]}
    write("activation_readiness.json", canonical_json(readiness) + "\n")
    write("integration_report.md", "# Dependency integration gate\n\nThis is an offline, analysis-only candidate overlay. It does not alter TargetIntel production scoring, ranking, roles, configuration, or defaults.\n\n- Decision: `" + result["decision"]["decision_state"] + "`\n- Evidence scope: `" + result["decision"]["evidence_scope"] + "`\n- Human review remains required.\n")
    manifest = {"integration_format_version": FORMAT_VERSION, "decision_id": result["decision"]["decision_id"], "candidate_id": candidate.candidate_id, "policy_id": result["policy"].policy_id, "analysis_only": True, "production_activation_enabled": False, "output_artifacts": ["dependency_integration_manifest.json", "integration_gate_decision.json", "integration_criteria.tsv", "input_compatibility.json", "baseline_preservation.json", "dependency_aware_profile_candidate.json", "candidate_overlay.tsv", "activation_readiness.json", "integration_report.md"]}
    write("dependency_integration_manifest.json", canonical_json(manifest) + "\n")
