"""Offline, analysis-only benchmarking of frozen DepMap dependency profiles.

This module deliberately does not import TargetIntel scoring, ranking, role,
feature, modality, card, report, or network surfaces.  It consumes immutable
artifacts and writes diagnostic rankings for human review only.
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

from .depmap_models import _forbidden_nested, _freeze, _identity, _thaw, canonical_json

POLICY_FORMAT_VERSION = "v0.5.0"
METRIC_DEFINITION_VERSION = "v0.5.0"


class DependencyBenchmarkError(ValueError):
    """Sanitized invalid-input or evaluation error."""


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise DependencyBenchmarkError(message)


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file(), f"required artifact is absent: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DependencyBenchmarkError("artifact could not be read") from exc
    _require(isinstance(data, dict), "JSON artifact must be an object")
    return data


def _read_tsv(path: Path) -> list[dict[str, str]]:
    _require(path.is_file(), f"required artifact is absent: {path.name}")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DependencyBenchmarkError("TSV artifact could not be read") from exc


def _number(value: Any, name: str) -> float:
    try: result = float(value)
    except (TypeError, ValueError) as exc: raise DependencyBenchmarkError(f"invalid {name}") from exc
    _require(math.isfinite(result), f"invalid {name}")
    return result


def _policy_has_dynamic_or_tuned_field(value: Any) -> bool:
    """Reject hidden callbacks, target-specific knobs, and outcome tuning."""
    markers = ("target_specific", "per_target", "benchmark_derived", "outcome_tuning", "tuning", "optimiz", "callback", "expression", "executable")
    if isinstance(value, Mapping):
        return any(any(marker in str(key).casefold() for marker in markers) or _policy_has_dynamic_or_tuned_field(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_policy_has_dynamic_or_tuned_field(item) for item in value)
    return False


@dataclass(frozen=True)
class DependencyBenchmarkPolicy:
    policy_format_version: str
    policy_id_label: str
    partitions: tuple[str, ...] | list[str]
    positive_classes: tuple[str, ...] | list[str]
    negative_classes: tuple[str, ...] | list[str]
    descriptive_classes: tuple[str, ...] | list[str]
    excluded_classes: tuple[str, ...] | list[str]
    primary_k_values: tuple[int, ...] | list[int]
    secondary_k_values: tuple[int, ...] | list[int]
    minimum_benchmark_coverage: float
    minimum_holdout_coverage: float
    minimum_eligible_targets: int
    exact_enrichment: Mapping[str, Any]
    multiple_testing_family: str
    candidate_rankings: Mapping[str, Any]
    source_ablations: Mapping[str, Any]
    rank_stability_thresholds: Mapping[str, Any]
    missing_profile_policy: str
    tie_handling_policy: str
    limitations: tuple[str, ...] | list[str]

    def __post_init__(self) -> None:
        for field in ("partitions", "positive_classes", "negative_classes", "descriptive_classes", "excluded_classes", "primary_k_values", "secondary_k_values", "limitations"):
            values = tuple(sorted(set(getattr(self, field))))
            object.__setattr__(self, field, values)
        object.__setattr__(self, "exact_enrichment", _freeze(dict(sorted(self.exact_enrichment.items()))))
        object.__setattr__(self, "candidate_rankings", _freeze(dict(sorted(self.candidate_rankings.items()))))
        object.__setattr__(self, "source_ablations", _freeze(dict(sorted(self.source_ablations.items()))))
        object.__setattr__(self, "rank_stability_thresholds", _freeze(dict(sorted(self.rank_stability_thresholds.items()))))
        _require(self.policy_format_version == POLICY_FORMAT_VERSION, "unsupported dependency-benchmark policy format")
        _require(self.partitions and set(self.partitions) <= {"development", "holdout", "combined"}, "invalid benchmark partitions")
        classes = set(self.positive_classes) | set(self.negative_classes) | set(self.descriptive_classes) | set(self.excluded_classes)
        _require(classes and not (set(self.positive_classes) & set(self.negative_classes)), "benchmark class mapping conflicts")
        _require(all(isinstance(k, int) and k > 0 for k in self.primary_k_values + self.secondary_k_values), "K values must be positive integers")
        _require(0 <= self.minimum_benchmark_coverage <= 1 and 0 <= self.minimum_holdout_coverage <= 1 and self.minimum_eligible_targets > 0, "invalid coverage or eligibility threshold")
        _require(self.missing_profile_policy == "retain_baseline_order_ineligible", "unsupported missing-profile policy")
        _require(self.tie_handling_policy == "midrank_signal_baseline_then_identity", "unsupported tie-handling policy")
        candidate = _thaw(self.candidate_rankings)
        _require(set(candidate) == {"dependency_only", "bounded_overlay"}, "candidate rankings must define dependency-only and bounded overlay")
        _require(candidate["bounded_overlay"].get("band_size", 0) > 0, "bounded overlay requires positive band size")
        _require(candidate["dependency_only"].get("minimum_component_count", 0) > 0, "dependency signal requires minimum component count")
        _require(set(_thaw(self.source_ablations)) >= {"all_components"}, "source ablations must include all_components")
        _require(not _forbidden_nested(self.identity_payload()), "policy contains credentials or hidden reasoning")
        _require(not _policy_has_dynamic_or_tuned_field(self.identity_payload()), "policy contains target-specific, benchmark-tuned, or executable fields")

    def identity_payload(self) -> dict[str, Any]:
        return {key: _thaw(getattr(self, key)) if key in {"exact_enrichment", "candidate_rankings", "source_ablations", "rank_stability_thresholds"} else list(getattr(self, key)) if isinstance(getattr(self, key), tuple) else getattr(self, key) for key in self.__dataclass_fields__}

    @property
    def policy_id(self) -> str: return _identity("dmbp", self.identity_payload())
    def to_dict(self) -> dict[str, Any]: return {**self.identity_payload(), "policy_id": self.policy_id}
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyBenchmarkPolicy":
        allowed = set(cls.__dataclass_fields__) | {"policy_id"}
        _require(set(data) <= allowed and set(cls.__dataclass_fields__) <= set(data), "unknown or missing benchmark-policy fields")
        item = cls(**{key: data[key] for key in cls.__dataclass_fields__})
        _require(data.get("policy_id") in (None, item.policy_id), "benchmark-policy identity does not match content")
        return item


def load_baseline_ranking(path: Path | str) -> tuple[list[dict[str, Any]], str, str]:
    """Load a neutral baseline artifact; labels are deliberately not accepted."""
    source = Path(path); rows = _read_tsv(source)
    _require(rows, "baseline ranking is empty")
    required = {"original_target_identifier", "canonical_target_identity", "baseline_rank", "primary_intent", "role"}
    _require(required <= set(rows[0]), "baseline ranking has missing required columns")
    result, seen, ranks = [], set(), set()
    for row in rows:
        identity = row["canonical_target_identity"].strip(); _require(identity and identity not in seen, "duplicate or empty baseline target identity")
        rank = _number(row["baseline_rank"], "baseline rank"); _require(rank > 0 and rank.is_integer() and int(rank) not in ranks, "baseline ranks must be unique positive integers")
        seen.add(identity); ranks.add(int(rank))
        result.append({"original_target_identifier": row["original_target_identifier"], "canonical_target_identity": identity, "baseline_rank": int(rank), "baseline_score": row.get("baseline_score") or None, "primary_intent": row["primary_intent"], "role": row["role"], "selected_state": row.get("selected_state") or None})
    result.sort(key=lambda r: r["baseline_rank"])
    _require([r["baseline_rank"] for r in result] == list(range(1, len(result) + 1)), "baseline ranks must be contiguous deterministic ordering")
    fingerprint = sha256(source.read_bytes()).hexdigest()
    return result, f"blr_{fingerprint}", fingerprint


def _profiles(profiles_dir: Path) -> tuple[dict[str, dict[str, Any]], str]:
    manifest = _read_json(profiles_dir / "dependency_profile_manifest.json")
    run_id = manifest.get("run_id"); _require(isinstance(run_id, str) and run_id, "dependency-profile run identity is required")
    records = {}
    path = profiles_dir / "dependency_profiles.jsonl"; _require(path.is_file(), "dependency profiles are absent")
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line); identity = record["target_identity"].get("canonical_identity") or record["target_identity"].get("normalized_request")
        # Issue 503 target identity currently carries its normalized request; use
        # matched canonical profile label only when present in profile payload.
        records[str(identity)] = record
    return records, run_id


def _profile_by_benchmark(profile_records: Mapping[str, dict[str, Any]], benchmark: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    by_request = {}
    for item in profile_records.values():
        target = item.get("target_identity", {})
        by_request[str(target.get("normalized_request", ""))] = item
        label = str(target.get("matched_original_source_label") or "")
        if " (" in label:
            by_request[label.split(" (", 1)[0]] = item
    return {row["canonical_identity"]: by_request[row["original_identifier"]] for row in benchmark if row["original_identifier"] in by_request}


def _percentiles(values: Mapping[str, float], higher: bool = True) -> dict[str, float]:
    if not values: return {}
    ordered = sorted(values.items(), key=lambda pair: (pair[1], pair[0]), reverse=higher)
    out = {}; count = len(ordered); i = 0
    while i < count:
        j = i + 1
        while j < count and ordered[j][1] == ordered[i][1]: j += 1
        rank = ((i + 1) + j) / 2
        for key, _ in ordered[i:j]: out[key] = 1.0 if count == 1 else 1 - (rank - 1) / (count - 1)
        i = j
    return out


def _signal(rows: list[dict[str, Any]], components: tuple[str, ...], minimum: int) -> None:
    raw: dict[str, dict[str, float]] = {}
    for row in rows:
        profile = row.get("profile")
        if not profile: continue
        payload = profile["payload"]; contrasts = payload["contrasts"]
        values = {
            "gene_effect_contrast": contrasts.get("gene_effect_context_minus_non_context_median"),
            "dependency_probability_contrast": contrasts.get("dependency_probability_context_minus_non_context_median"),
            "lineage_position": payload.get("empirical_context_lineage_position", {}).get("value"),
        }
        raw[row["canonical_identity"]] = {key: float(value) for key, value in values.items() if key in components and value is not None}
    per_component = {}
    for component in components:
        vals = {key: (-value if component == "gene_effect_contrast" else value) for key, item in raw.items() if (value := item.get(component)) is not None}
        per_component[component] = _percentiles(vals)
    for row in rows:
        key = row["canonical_identity"]; values = [per_component[c][key] for c in components if key in per_component[c]]
        row["component_count"] = len(values); row["dependency_signal"] = sum(values) / len(values) if len(values) >= minimum else None
        row["ineligible_reason"] = None if row["dependency_signal"] is not None else "insufficient_dependency_components"


def _rank(rows: list[dict[str, Any]], name: str, *, overlay: bool, band_size: int = 0) -> None:
    if overlay:
        # Bands are positions in the complete baseline artifact, not positions
        # in the reconciled benchmark subset.  The latter can have gaps because
        # benchmark targets are only a subset of the baseline ranking.
        bands: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            if row["baseline_rank"] is not None:
                bands.setdefault((row["baseline_rank"] - 1) // band_size, []).append(row)
        for band_index in sorted(bands):
            band = sorted(bands[band_index], key=lambda r: r["baseline_rank"])
            eligible = sorted((r for r in band if r["dependency_signal"] is not None), key=lambda r: (-r["dependency_signal"], r["baseline_rank"], r["canonical_identity"]))
            iterator = iter(eligible)
            # Only eligible targets are locally reordered.  Ineligible targets
            # and every unrepresented baseline target retain their baseline
            # positions, so no target can leave its numeric baseline band.
            for row in band:
                replacement = next(iterator) if row["dependency_signal"] is not None else row
                replacement[name] = row["baseline_rank"]
    else:
        ordered = sorted((r for r in rows if r["baseline_rank"] is not None), key=lambda r: (r["dependency_signal"] is None, -(r["dependency_signal"] or 0), r["baseline_rank"], r["canonical_identity"]))
        for index, row in enumerate(ordered, 1): row[name] = index
    for row in rows:
        row.setdefault(name, None)


def _metrics(rows: list[dict[str, Any]], partition: str, ranking: str, policy: DependencyBenchmarkPolicy) -> list[dict[str, Any]]:
    subset = [r for r in rows if partition == "combined" or r["partition"] == partition]
    eligible = [r for r in subset if r["benchmark_class"] in set(policy.positive_classes) | set(policy.negative_classes)]
    positives = [r for r in eligible if r["benchmark_class"] in policy.positive_classes]
    negatives = [r for r in eligible if r["benchmark_class"] in policy.negative_classes]
    ranked = sorted((r for r in eligible if r.get(ranking) is not None), key=lambda r: r[ranking])
    ranked_positives = [r for r in positives if r.get(ranking) is not None]
    base = {"partition": partition, "ranking": ranking, "eligible_target_count": len(eligible), "ranked_target_count": len(ranked), "positive_count": len(positives), "negative_count": len(negatives), "coverage_fraction": len(ranked) / len(eligible) if eligible else None}
    output=[]
    for k in policy.primary_k_values + policy.secondary_k_values:
        top = ranked[:k]; pos = sum(r["benchmark_class"] in policy.positive_classes for r in top); neg = sum(r["benchmark_class"] in policy.negative_classes for r in top)
        output.append({**base, "k": k, "recall_at_k": pos / len(positives) if positives else None, "precision_at_k": pos / len(top) if top else None, "positive_top_k_count": pos, "negative_top_k_count": neg, "negative_exclusion_outside_top_k": (len(negatives)-neg) / len(negatives) if negatives else None, "average_precision": sum((sum(x["benchmark_class"] in policy.positive_classes for x in ranked[:i]) / i) for i, x in enumerate(ranked,1) if x["benchmark_class"] in policy.positive_classes) / len(positives) if positives else None, "mean_reciprocal_rank": 1 / min(r[ranking] for r in ranked_positives) if ranked_positives else None, "median_rank": median([r[ranking] for r in ranked_positives]) if ranked_positives else None, "normalized_median_rank": median([r[ranking] for r in ranked_positives]) / len(ranked) if ranked_positives and ranked else None})
    return output


def _stability(rows: list[dict[str, Any]], ranking: str, k: int, band_size: int | None = None) -> dict[str, Any]:
    shared = [r for r in rows if r.get(ranking) is not None]
    changes = [abs(r[ranking] - r["baseline_rank"]) for r in shared]
    # Pearson correlation of rank vectors is Spearman for ranks.
    def corr(a, b):
        if len(a) < 2: return None
        ma, mb = sum(a)/len(a), sum(b)/len(b); den = math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
        return sum((x-ma)*(y-mb) for x,y in zip(a,b)) / den if den else None
    baseline_top={r["canonical_identity"] for r in sorted(shared,key=lambda r:r["baseline_rank"])[:k]}; candidate_top={r["canonical_identity"] for r in sorted(shared,key=lambda r:r[ranking])[:k]}
    return {"ranking": ranking, "shared_target_count": len(shared), "spearman_rank_correlation": corr([r["baseline_rank"] for r in shared],[r[ranking] for r in shared]), "top_k":k,"top_k_jaccard":len(baseline_top&candidate_top)/len(baseline_top|candidate_top) if baseline_top|candidate_top else None,"top_k_retained_count":len(baseline_top&candidate_top),"top_k_added_count":len(candidate_top-baseline_top),"top_k_removed_count":len(baseline_top-candidate_top),"median_absolute_rank_change":median(changes) if changes else None,"maximum_absolute_rank_change":max(changes,default=None),"band_violations":sum((r["baseline_rank"]-1)//band_size != (r[ranking]-1)//band_size for r in shared) if band_size else None}


def _hypergeometric_tail(population: int, successes: int, draws: int, observed: int) -> float | None:
    """One-sided enrichment probability, retained as exploratory only."""
    if min(population, successes, draws, observed) < 0 or successes > population or draws > population:
        return None
    denominator = math.comb(population, draws)
    if not denominator: return None
    return sum(math.comb(successes, value) * math.comb(population - successes, draws - value) for value in range(max(observed, draws - (population - successes)), min(successes, draws) + 1)) / denominator


def _integration_evidence(
    rows: list[dict[str, Any]],
    bounded_overlay_stability: Mapping[str, Any],
    policy: DependencyBenchmarkPolicy,
) -> dict[str, Any]:
    """Evaluate only the predeclared, descriptive Issue 506 handoff criteria."""
    holdout_rows = [row for row in rows if row["partition"] == "holdout"]
    holdout_profiled = sum(row["profile"] is not None for row in holdout_rows)
    holdout_coverage = (
        holdout_profiled / len(holdout_rows) if holdout_rows else None
    )
    return {
        "status": "human_review_required",
        "criteria": [
            {
                "criterion": "zero_bounded_overlay_band_violations",
                "observed": bounded_overlay_stability["band_violations"],
                "threshold": 0,
                "status": (
                    "pass"
                    if bounded_overlay_stability["band_violations"] == 0
                    else "fail"
                ),
            },
            {
                "criterion": "minimum_holdout_coverage",
                "observed": holdout_coverage,
                "threshold": policy.minimum_holdout_coverage,
                "numerator": holdout_profiled,
                "denominator": len(holdout_rows),
                "status": (
                    "unavailable"
                    if holdout_coverage is None
                    else "pass"
                    if holdout_coverage >= policy.minimum_holdout_coverage
                    else "fail"
                ),
            },
        ],
    }


@dataclass(frozen=True)
class DependencyBenchmarkEvaluation:
    manifest: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]
    metrics: tuple[Mapping[str, Any], ...]
    def __post_init__(self): object.__setattr__(self,"manifest",_freeze(self.manifest)); object.__setattr__(self,"rows",tuple(_freeze(x) for x in self.rows)); object.__setattr__(self,"metrics",tuple(_freeze(x) for x in self.metrics))


def evaluate_dependency_benchmark(universe_dir: Path | str, profiles_dir: Path | str, baseline_ranking: Path | str, policy: DependencyBenchmarkPolicy) -> DependencyBenchmarkEvaluation:
    universe, profile_dir = Path(universe_dir), Path(profiles_dir)
    freeze = _read_json(universe / "universe_freeze_manifest.json"); freeze_id = freeze.get("freeze_id"); _require(isinstance(freeze_id,str) and freeze_id, "frozen-universe identity is required")
    benchmark = _read_tsv(universe / "benchmark_universe.tsv"); discovery={r["canonical_identity"] for r in _read_tsv(universe / "discovery_universe.tsv")}; background={r["canonical_identity"] for r in _read_tsv(universe / "background_universe.tsv")}
    baseline, baseline_id, fingerprint_before = load_baseline_ranking(baseline_ranking); profiles, profile_run_id = _profiles(profile_dir); matched = _profile_by_benchmark(profiles, benchmark); base_map={r["canonical_target_identity"]:r for r in baseline}
    rows=[]
    for item in benchmark:
        identity=item["canonical_identity"]; base=base_map.get(identity); profile=matched.get(identity)
        state="ranked_and_profiled" if base and profile else "ranked_not_profiled" if base else "profiled_not_ranked" if profile else "unresolved_benchmark_target"
        row={"canonical_identity":identity,"original_identifier":item["original_identifier"],"benchmark_class":item["benchmark_class"],"partition":item["partition"],"resistance_axes":item["resistance_axes"],"reconciliation_state":state,"absent_from_discovery":identity not in discovery,"absent_from_background":identity not in background,"profile":profile,"baseline_rank":base["baseline_rank"] if base else None,"baseline_score":base["baseline_score"] if base else None,"primary_intent":base["primary_intent"] if base else None,"role":base["role"] if base else None}
        rows.append(row)
    components=tuple(_thaw(policy.source_ablations)["all_components"])
    _signal(rows,components,int(_thaw(policy.candidate_rankings)["dependency_only"]["minimum_component_count"])); _rank(rows,"dependency_only_rank",overlay=False); band=int(_thaw(policy.candidate_rankings)["bounded_overlay"]["band_size"]); _rank(rows,"bounded_overlay_rank",overlay=True,band_size=band)
    fingerprint_after=sha256(Path(baseline_ranking).read_bytes()).hexdigest(); _require(fingerprint_before==fingerprint_after,"baseline artifact changed during benchmarking")
    metrics=[]
    for ranking in ("baseline_rank","dependency_only_rank","bounded_overlay_rank"):
        metrics.extend(_metrics(rows,"development",ranking,policy)); metrics.extend(_metrics(rows,"holdout",ranking,policy)); metrics.extend(_metrics(rows,"combined",ranking,policy))
    manifest={"evaluation_format_version":METRIC_DEFINITION_VERSION,"freeze_id":freeze_id,"benchmark_universe_id":freeze.get("benchmark_universe_id"),"dependency_profile_run_id":profile_run_id,"baseline_ranking_id":baseline_id,"baseline_fingerprint":fingerprint_before,"policy_id":policy.policy_id,"metric_definition_version":METRIC_DEFINITION_VERSION,"candidate_ranking_ids":{"dependency_only":_identity("dmbr",{"policy_id":policy.policy_id,"name":"dependency_only","rows":[(r["canonical_identity"],r["dependency_only_rank"]) for r in rows]}),"bounded_overlay":_identity("dmbr",{"policy_id":policy.policy_id,"name":"bounded_overlay","rows":[(r["canonical_identity"],r["bounded_overlay_rank"]) for r in rows]})},"analysis_only":True,"integration_status":"human_review_required"}
    return DependencyBenchmarkEvaluation(manifest,tuple(rows),tuple(metrics))


def write_dependency_benchmark_artifacts(output_dir: Path | str, evaluation: DependencyBenchmarkEvaluation, policy: DependencyBenchmarkPolicy) -> None:
    output=Path(output_dir); _require(output.is_absolute(),"output directory must be explicit and absolute"); output.mkdir(parents=True,exist_ok=True)
    rows=[_thaw(r) for r in evaluation.rows]; metrics=[_thaw(m) for m in evaluation.metrics]
    def write(name,text):
        tmp=output/f".{name}.tmp"; tmp.write_text(text,encoding="utf-8",newline=""); tmp.replace(output/name)
    coverage={"total_benchmark_targets":len(rows),"ranked_target_count":sum(r["baseline_rank"] is not None for r in rows),"profiled_target_count":sum(r["profile"] is not None for r in rows),"reconciliation_counts":{key:sum(r["reconciliation_state"]==key for r in rows) for key in sorted({r["reconciliation_state"] for r in rows})}}
    candidate={"analysis_only":True,"rank_stability":[_stability(rows,"dependency_only_rank",policy.primary_k_values[0]),_stability(rows,"bounded_overlay_rank",policy.primary_k_values[0],int(_thaw(policy.candidate_rankings)["bounded_overlay"]["band_size"]))],"limitations":["Diagnostic fixture results are not scientific findings."]}
    axes=[]
    for axis in sorted({a for r in rows for a in r["resistance_axes"].split("|") if a}):
        subset = [r for r in rows if axis in r["resistance_axes"].split("|")]
        baseline_ranks = [r["baseline_rank"] for r in subset if r["baseline_rank"] is not None]
        candidate_ranks = [
            r["dependency_only_rank"]
            for r in subset
            if r["dependency_only_rank"] is not None
        ]
        axes.append({"resistance_axis":axis,"target_count":len(subset),"positive_count":sum(r["benchmark_class"] in policy.positive_classes for r in subset),"negative_count":sum(r["benchmark_class"] in policy.negative_classes for r in subset),"descriptive_count":sum(r["benchmark_class"] in policy.descriptive_classes for r in subset),"median_baseline_rank":median(baseline_ranks) if baseline_ranks else None,"median_candidate_rank":median(candidate_ranks) if candidate_ranks else None,"sufficient":len(subset)>=policy.minimum_eligible_targets})
    def tsv(name, items):
        fields=sorted({key for x in items for key in x if key != "profile"}); write(name,"\t".join(fields)+"\n"+"".join("\t".join("" if x.get(k) is None else str(x.get(k)) for k in fields)+"\n" for x in items))
    write("benchmark_coverage.json",canonical_json(coverage)+"\n"); write("baseline_metrics.json",canonical_json([m for m in metrics if m["ranking"]=="baseline_rank"])+"\n"); write("candidate_metrics.json",canonical_json({"metrics":[m for m in metrics if m["ranking"]!="baseline_rank"],**candidate})+"\n")
    tsv("rank_comparison.tsv",[{k:v for k,v in r.items() if k not in {"profile"}} for r in rows]); tsv("control_results.tsv",[{"canonical_identity":r["canonical_identity"],"benchmark_class":r["benchmark_class"],"partition":r["partition"],"baseline_rank":r["baseline_rank"],"dependency_only_rank":r["dependency_only_rank"],"bounded_overlay_rank":r["bounded_overlay_rank"],"dependency_signal":r["dependency_signal"],"ineligible_reason":r["ineligible_reason"],"common_essential_reference_state":r["profile"]["payload"]["common_essential_reference"]["status"] if r["profile"] else "reference_unavailable","pan_dependency_reference_state":r["profile"]["payload"]["pan_dependency_reference"]["status"] if r["profile"] else "reference_unavailable"} for r in rows]); tsv("partition_metrics.tsv",metrics); tsv("resistance_axis_metrics.tsv",axes)
    ablations=[]
    minimum=int(_thaw(policy.candidate_rankings)["dependency_only"]["minimum_component_count"])
    for name, components in sorted(_thaw(policy.source_ablations).items()):
        variant=[dict(r) for r in rows]
        _signal(variant, tuple(components), minimum); _rank(variant, "ablation_rank", overlay=False)
        stability=_stability(variant, "ablation_rank", policy.primary_k_values[0])
        ablations.append({"ablation":name,"available_components":"|".join(components),"eligible_target_count":sum(r["component_count"]>=minimum and r["baseline_rank"] is not None for r in variant),"rank_identity":_identity("dmbr", {"policy_id":policy.policy_id,"ablation":name,"rows":[(r["canonical_identity"],r["ablation_rank"]) for r in variant]}),"spearman_vs_baseline":stability["spearman_rank_correlation"],"top_k_jaccard_vs_baseline":stability["top_k_jaccard"],"analysis_only":True,"limitations":"Predeclared source ablation; not benchmark-guided selection."})
    tsv("ablation_metrics.tsv",ablations)
    enrichment=[]
    for metric in [m for m in metrics if m["ranking"] in {"baseline_rank", "dependency_only_rank", "bounded_overlay_rank"}]:
        population=metric["eligible_target_count"]; successes=metric["positive_count"]; draws=min(metric["k"],metric["ranked_target_count"]); observed=metric["positive_top_k_count"]
        value=_hypergeometric_tail(population,successes,draws,observed) if population >= _thaw(policy.exact_enrichment).get("minimum_population", 1) else None
        enrichment.append({"partition":metric["partition"],"ranking":metric["ranking"],"k":metric["k"],"population":population,"success_count":successes,"draw_count":draws,"observed_count":observed,"raw_p_value":value,"adjusted_p_value":min(1.0,value*len(metrics)) if value is not None else None,"exploratory":True})
    write("enrichment_results.json",canonical_json({"exploratory":True,"multiple_testing_family":policy.multiple_testing_family,"results":enrichment})+"\n")
    integration = _integration_evidence(
        rows, candidate["rank_stability"][1], policy
    )
    write("integration_evidence.json", canonical_json(integration) + "\n")
    write("benchmark_report.md","# Dependency benchmark (analysis only)\n\nThis offline synthetic analysis is exploratory, not clinical or causal validation. It does not enable a production dependency-aware ranking. Human review is required.\n")
    # Success manifest is deliberately written last.
    write("dependency_benchmark_manifest.json",canonical_json({**_thaw(evaluation.manifest),"output_artifacts":["dependency_benchmark_manifest.json","benchmark_coverage.json","baseline_metrics.json","candidate_metrics.json","rank_comparison.tsv","control_results.tsv","partition_metrics.tsv","resistance_axis_metrics.tsv","ablation_metrics.tsv","enrichment_results.json","integration_evidence.json","benchmark_report.md"]})+"\n")
