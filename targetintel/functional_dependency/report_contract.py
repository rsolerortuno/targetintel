"""Immutable, portable evidence for optional DepMap report rendering.

This contract consumes already-loaded, small portable records only.  It does
not read files, discover an environment, calculate profiles, or alter ranks.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping


REPORT_EVIDENCE_FORMAT_VERSION = "v1"
_COVERAGE_STATUSES = frozenset({
    "not_available", "sufficient_complete_coverage", "sufficient_partial_coverage",
    "no_context_models", "context_models_all_values_missing",
    "insufficient_measured_context_models", "insufficient_measured_reference_models",
    "target_unresolved", "target_present_only_gene_effect",
    "target_present_only_dependency_probability",
})
_LOCAL_PATH = re.compile(r"(?:/home/|/media/|/mnt/|/tmp/|/Users/|/Volumes/|(?:^|[^A-Za-z])[A-Za-z]:[\\/])")


def _fail(field: str, message: str) -> None:
    raise ValueError(f"{field} {message}")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(field, "must be a non-empty string")
    return value


def _freeze(value: Any, field: str = "structured value") -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(field, "mapping keys must be strings")
            frozen[key] = _freeze(item, field)
        return MappingProxyType({key: frozen[key] for key in sorted(frozen)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, field) for item in value)
    if isinstance(value, bool) or value is None or isinstance(value, str) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(field, "must not contain NaN or infinity")
        return value
    _fail(field, f"contains unsupported value type {type(value).__name__}")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    return json.dumps(_plain(_freeze(value)), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _integer(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        _fail(field, "must be a non-negative integer or null")
    return value


def _rank(value: Any, field: str) -> int | None:
    result = _integer(value, field)
    if result == 0:
        _fail(field, "must be a positive integer or null")
    return result


def _number(value: Any, field: str) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(field, "must be a finite number or null")
    return value


def _portable(value: Any, field: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _portable(key, field); _portable(item, field)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _portable(item, field)
    elif isinstance(value, str) and _LOCAL_PATH.search(value):
        _fail(field, "must not contain a local path")


def _artifact_name(value: Any) -> str:
    value = _text(value, "provenance.source_artifact_names")
    if "\\" in value or "://" in value:
        _fail("provenance.source_artifact_names", "must contain portable relative artifact names")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        _fail("provenance.source_artifact_names", "must contain portable relative artifact names")
    return value


@dataclass(frozen=True)
class DependencyReportEvidence:
    """Read-only report boundary for one target's validated DepMap evidence.

    ``rank_delta`` follows the bounded-overlay convention as
    ``dependency_aware_candidate_rank - baseline_rank``: a negative value is
    an observed improvement.  It is validated only; no rank is calculated.
    """

    format_version: str
    evidence_id: str
    release_identifier: str
    release_manifest_id: str
    configuration_id: str
    scientific_closure_identity: str
    context_identity: str
    gene_symbol: str
    canonical_gene_identity: str | None
    profile_available: bool
    coverage_status: str
    model_count: int | None
    context_model_count: int | None
    reference_model_count: int | None
    available_context_observations: int | None
    available_reference_observations: int | None
    coverage_fraction: float | int | None
    missing_value_state: str | None
    unavailable_reason: str | None
    gene_effect: Mapping[str, Any] | None
    dependency_probability: Mapping[str, Any] | None
    context_reference_comparison: Mapping[str, Any] | None
    selectivity: Mapping[str, Any] | None
    dependency_interpretation_state: str | None
    baseline_rank: int | None
    dependency_aware_candidate_rank: int | None
    rank_delta: int | None
    integration_state: str | None
    baseline_preserved: bool
    production_activation_enabled: bool
    approved_authorization_emitted: bool
    candidate_activation_readiness: str | None
    human_review_required: bool
    limitations: tuple[str, ...] | list[str]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.format_version != REPORT_EVIDENCE_FORMAT_VERSION:
            _fail("format_version", "is unsupported")
        for name in ("release_identifier", "release_manifest_id", "configuration_id", "scientific_closure_identity", "context_identity", "gene_symbol"):
            _text(getattr(self, name), name)
        if not isinstance(self.profile_available, bool): _fail("profile_available", "must be boolean")
        if self.coverage_status not in _COVERAGE_STATUSES: _fail("coverage_status", "is invalid")
        for name in ("model_count", "context_model_count", "reference_model_count", "available_context_observations", "available_reference_observations"):
            object.__setattr__(self, name, _integer(getattr(self, name), name))
        object.__setattr__(self, "coverage_fraction", _number(self.coverage_fraction, "coverage_fraction"))
        if self.coverage_fraction is not None and not 0 <= self.coverage_fraction <= 1:
            _fail("coverage_fraction", "must be between 0 and 1")
        for observations, models, label in ((self.available_context_observations, self.context_model_count, "available_context_observations"), (self.available_reference_observations, self.reference_model_count, "available_reference_observations")):
            if observations is not None and models is not None and observations > models:
                _fail(label, "must not exceed its model count")
        if self.canonical_gene_identity is not None: _text(self.canonical_gene_identity, "canonical_gene_identity")
        for name in ("missing_value_state", "unavailable_reason", "dependency_interpretation_state", "integration_state", "candidate_activation_readiness"):
            value = getattr(self, name)
            if value is not None: _text(value, name)
        structured = ("gene_effect", "dependency_probability", "context_reference_comparison", "selectivity")
        for name in structured:
            value = getattr(self, name)
            if value is not None and not isinstance(value, Mapping): _fail(name, "must be a mapping or null")
            object.__setattr__(self, name, None if value is None else _freeze(value, name))
        unavailable = not self.profile_available or self.coverage_status == "not_available"
        if unavailable:
            if self.profile_available or self.coverage_status != "not_available":
                _fail("coverage_status", "not_available must describe an unavailable profile")
            if any(getattr(self, name) is not None for name in structured): _fail("profile_available", "unavailable profiles must not contain dependency metrics")
            if self.unavailable_reason is None: _fail("unavailable_reason", "is required for an unavailable profile")
            if any(getattr(self, name) is not None for name in ("canonical_gene_identity", "model_count", "context_model_count", "reference_model_count", "available_context_observations", "available_reference_observations", "coverage_fraction")):
                _fail("profile_available", "unavailable profiles must use explicit absent coverage values")
        else:
            if not self.canonical_gene_identity: _fail("canonical_gene_identity", "is required for an available profile")
            if self.model_count is None or self.context_model_count is None or self.reference_model_count is None or self.available_context_observations is None or self.available_reference_observations is None or self.coverage_fraction is None:
                _fail("coverage", "available profiles require counts and coverage_fraction")
            if self.model_count < self.context_model_count + self.reference_model_count:
                _fail("model_count", "must cover context and reference model counts")
        for name in ("baseline_rank", "dependency_aware_candidate_rank"):
            object.__setattr__(self, name, _rank(getattr(self, name), name))
        if self.rank_delta is not None and (not isinstance(self.rank_delta, int) or isinstance(self.rank_delta, bool)):
            _fail("rank_delta", "must be an integer or null")
        if self.baseline_rank is not None and self.dependency_aware_candidate_rank is not None:
            expected = self.dependency_aware_candidate_rank - self.baseline_rank
            if self.rank_delta != expected: _fail("rank_delta", "does not equal dependency_aware_candidate_rank minus baseline_rank")
        elif self.rank_delta is not None: _fail("rank_delta", "requires both ranks")
        if self.baseline_preserved is not True: _fail("baseline_preserved", "must be true")
        if self.production_activation_enabled is not False: _fail("production_activation_enabled", "must be false")
        if self.approved_authorization_emitted is not False: _fail("approved_authorization_emitted", "must be false")
        if self.human_review_required is not True: _fail("human_review_required", "must be true")
        limitations = tuple(self.limitations)
        if not limitations or any(not isinstance(item, str) or not item.strip() for item in limitations): _fail("limitations", "must contain non-empty strings")
        object.__setattr__(self, "limitations", tuple(sorted(set(limitations))))
        if not isinstance(self.provenance, Mapping): _fail("provenance", "must be a mapping")
        frozen_provenance = _freeze(self.provenance, "provenance"); _portable(frozen_provenance, "provenance")
        artifacts = frozen_provenance.get("source_artifact_names")
        if not isinstance(artifacts, tuple) or not artifacts:
            _fail("provenance.source_artifact_names", "must be a non-empty sequence")
        normalized_artifacts = tuple(sorted(set(_artifact_name(item) for item in artifacts)))
        object.__setattr__(self, "provenance", MappingProxyType({
            **{key: value for key, value in frozen_provenance.items() if key != "source_artifact_names"},
            "source_artifact_names": normalized_artifacts,
        }))
        if self.evidence_id != self._identity(): _fail("evidence_id", "does not match deterministic scientific payload")

    def identity_payload(self) -> dict[str, Any]:
        return {name: _plain(getattr(self, name)) for name in self.__dataclass_fields__ if name not in {"evidence_id", "provenance"}}

    def _identity(self) -> str:
        return "drep_" + sha256(_canonical(self.identity_payload()).encode("utf-8")).hexdigest()

    @classmethod
    def create(cls, **values: Any) -> "DependencyReportEvidence":
        values = dict(values)
        values.pop("evidence_id", None)
        if "limitations" in values:
            values["limitations"] = tuple(sorted(set(values["limitations"])))
        provisional = dict(values)
        provisional["evidence_id"] = ""
        # Freeze/normalize through a temporary identity payload without
        # retaining caller-owned values.
        payload = {name: provisional[name] for name in cls.__dataclass_fields__ if name not in {"evidence_id", "provenance"}}
        values["evidence_id"] = "drep_" + sha256(_canonical(payload).encode("utf-8")).hexdigest()
        return cls(**values)

    def to_dict(self) -> dict[str, Any]:
        return {name: _plain(getattr(self, name)) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyReportEvidence":
        if not isinstance(data, Mapping): _fail("data", "must be a mapping")
        fields = set(cls.__dataclass_fields__)
        if set(data) != fields: _fail("data", "has unknown or missing contract fields")
        return cls(**dict(data))


def build_dependency_report_evidence(*, release_summary: Mapping[str, Any], profile_record: Mapping[str, Any] | None,
                                     overlay_record: Mapping[str, Any] | None, provenance: Mapping[str, Any]) -> DependencyReportEvidence:
    """Pure adapter from explicit Issue 508-style portable records."""
    if not isinstance(release_summary, Mapping) or not isinstance(provenance, Mapping): _fail("input", "must be mappings")
    profile = {} if profile_record is None else dict(profile_record)
    overlay = {} if overlay_record is None else dict(overlay_record)
    for field in ("release_manifest_id", "context_identity"):
        profile_value = profile.get(field)
        summary_value = release_summary.get(field)
        if profile_value is not None and summary_value is not None and profile_value != summary_value:
            _fail(field, "is incompatible between profile_record and release_summary")
    payload = profile.get("payload", profile)
    if not isinstance(payload, Mapping): _fail("profile_record", "payload must be a mapping")
    target = profile.get("target_identity", {})
    if not isinstance(target, Mapping): target = {}
    status = payload.get("coverage_status", "not_available")
    available = status != "not_available"
    coverage = payload.get("model_coverage", {}) if isinstance(payload.get("model_coverage", {}), Mapping) else {}
    summaries = payload.get("summaries", {}) if isinstance(payload.get("summaries", {}), Mapping) else {}
    context = summaries.get("context", {}) if isinstance(summaries.get("context", {}), Mapping) else {}
    reference = summaries.get("non_context", {}) if isinstance(summaries.get("non_context", {}), Mapping) else {}
    effect = context.get("gene_effect") if isinstance(context, Mapping) else None
    probability = context.get("dependency_probability") if isinstance(context, Mapping) else None
    context_observations = effect.get("measured_model_count") if isinstance(effect, Mapping) else None
    reference_effect = reference.get("gene_effect") if isinstance(reference, Mapping) else None
    reference_observations = reference_effect.get("measured_model_count") if isinstance(reference_effect, Mapping) else None
    context_models = coverage.get("context_model_count")
    coverage_fraction = None if context_models in (None, 0) or context_observations is None else context_observations / context_models
    gene_symbol = target.get("normalized_request") or profile.get("target") or release_summary.get("gene_symbol")
    canonical = target.get("canonical_identity") or target.get("matched_original_source_label") or profile.get("canonical_gene_identity")
    overlay_canonical = overlay.get("canonical_target_identity")
    if overlay_canonical is not None and canonical is not None and overlay_canonical != canonical:
        _fail("overlay_record.canonical_target_identity", "is incompatible with profile_record target identity")
    overlay_original = overlay.get("original_target_identifier")
    if overlay_original is not None and gene_symbol is not None and overlay_original != gene_symbol:
        _fail("overlay_record.original_target_identifier", "is incompatible with profile_record target identity")
    values = {
        "format_version": REPORT_EVIDENCE_FORMAT_VERSION, "release_identifier": release_summary.get("release_identifier"), "release_manifest_id": release_summary.get("release_manifest_id"), "configuration_id": release_summary.get("configuration_id"), "scientific_closure_identity": release_summary.get("scientific_closure_identity"), "context_identity": release_summary.get("context_identity"), "gene_symbol": gene_symbol, "canonical_gene_identity": canonical if available else None, "profile_available": available, "coverage_status": status, "model_count": coverage.get("pan_cancer_model_count"), "context_model_count": context_models, "reference_model_count": coverage.get("non_context_model_count"), "available_context_observations": context_observations, "available_reference_observations": reference_observations, "coverage_fraction": coverage_fraction, "missing_value_state": payload.get("matrix_coverage_status"), "unavailable_reason": None if available else payload.get("target_resolution_status", "profile_not_available"), "gene_effect": effect if available else None, "dependency_probability": probability if available else None, "context_reference_comparison": payload.get("contrasts") if available else None, "selectivity": payload.get("empirical_context_lineage_position") if available else None, "dependency_interpretation_state": profile.get("terminal_status"), "baseline_rank": overlay.get("baseline_rank"), "dependency_aware_candidate_rank": overlay.get("candidate_rank"), "rank_delta": None, "integration_state": release_summary.get("integration_state"), "baseline_preserved": release_summary.get("baseline_preserved"), "production_activation_enabled": release_summary.get("production_activation_enabled"), "approved_authorization_emitted": release_summary.get("approved_authorization_emitted"), "candidate_activation_readiness": release_summary.get("candidate_activation_readiness"), "human_review_required": release_summary.get("human_review_required"), "limitations": tuple(release_summary.get("limitations", ())) + tuple(payload.get("limitations", ())), "provenance": provenance,
    }
    if values["baseline_rank"] is not None and values["dependency_aware_candidate_rank"] is not None:
        values["rank_delta"] = values["dependency_aware_candidate_rank"] - values["baseline_rank"]
    return DependencyReportEvidence.create(**values)
