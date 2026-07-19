"""Sequential association and directed Open Targets source ingestion."""
from __future__ import annotations
from typing import Any, Mapping
from .opentargets_models import (OpenTargetsFetchRequest, OpenTargetsTargetResolution, OpenTargetsTargetRecord, OpenTargetsTransportResponse, OpenTargetsCoverageReport, OpenTargetsFetchResult, RELEASE_VERIFICATION_STATES)
from .opentargets_queries import build_execution_query_plan, build_query_plan
from .opentargets_cache import cache_identity, cache_lookup_identity, OpenTargetsCache
from .opentargets_transport import OpenTargetsTransport, FakeOpenTargetsTransport

def _release(request, responses):
    observed=next((r.source_release for r in responses if r.source_release),None)
    if not observed:
        state = "declared_unverified" if request.requested_source_release != "not_reported" else "not_reported"
    elif request.requested_source_release == "not_reported":
        state = "declared_unverified"
    else:
        state = "verified" if observed == request.requested_source_release else "mismatch"
    return observed or request.requested_source_release, state
def _target(data: Mapping[str,Any]):
    payload_data = data.get("data") if isinstance(data, Mapping) else None
    return payload_data.get("target") if isinstance(payload_data, Mapping) else None
def _record(request, target, response, release, state, disease_id=None, association=None):
    fields={k:target.get(k) for k in ("biotype","tractability","safetyLiabilities","knownDrugs") if k in target}
    return OpenTargetsTargetRecord(request_id=request.request_id,target_id=target.get("id"),ensembl_gene_id=target.get("id"),approved_symbol=target.get("approvedSymbol"),approved_name=target.get("approvedName"),disease_id=disease_id,association=association,source_fields=fields,source_release=release,release_verification_state=state,source_query_id=response.operation_id,raw_payload_id=response.payload_id)
def _response_bad(r): return r.status_code < 200 or r.status_code >= 300 or not isinstance(r.payload,Mapping)
def _result(request, plan, status, resolutions, records, categories, responses, errors=(), execution_operations=()):
    execution_plan = build_execution_query_plan(request, tuple(execution_operations))
    release, state=_release(request,responses)
    observed_release=next((r.source_release for r in responses if r.source_release),None)
    if state=="mismatch" and request.release_verification_required: status="release_mismatch"
    trunc=status=="truncated"
    coverage=OpenTargetsCoverageReport(request.request_id,request.query_type,categories,truncated=trunc)
    return OpenTargetsFetchResult(status=status,request=request,query_plan=execution_plan,cache_identity=cache_identity(request,execution_plan,release,state),release_verification_state=state,resolutions=resolutions,records=records,coverage_report=coverage,error_codes=errors,observed_source_release=observed_release)

def _with_origin(result, origin):
    return OpenTargetsFetchResult(
        status=result.status, request=result.request, query_plan=result.query_plan,
        cache_identity=result.cache_identity,
        release_verification_state=result.release_verification_state,
        resolutions=result.resolutions, records=result.records,
        coverage_report=result.coverage_report, error_codes=result.error_codes,
        cache_origin=origin, observed_source_release=result.observed_source_release,
    )

def _cached_responses(value):
    responses = {}
    for item in value.get("responses", []):
        payload=item["payload"]
        if item.get("payload_sha256") != OpenTargetsTransportResponse(
            operation_id=item["operation_id"], status_code=item["status_code"], payload=payload
        ).payload_sha256:
            raise ValueError("cached_payload_hash_mismatch")
        responses[item["operation_id"]] = OpenTargetsTransportResponse(
            operation_id=item["operation_id"], status_code=item["status_code"],
            payload=payload, source_release=item.get("source_release"),
            error_codes=item.get("error_codes", ()), retry_count=item.get("retry_count", 0))
    return responses

def fetch_opentargets(request: OpenTargetsFetchRequest, transport: OpenTargetsTransport, cache: OpenTargetsCache | None = None) -> OpenTargetsFetchResult:
    """Fetch a code-owned plan through an injected transport, with no scoring/ranking.

    This deliberately has no cache argument: cache policy is represented in the
    request and storage is an explicit optional wrapper, preventing implicit IO.
    """
    plan=build_query_plan(request)
    # The release-aware physical key cannot be known before a source response.
    # Lookup instead uses every stable request/plan component and accepts one
    # unambiguous manifest; the selected manifest still retains its full
    # release-aware cache identity and verification state.
    lookup_key = cache_lookup_identity(request, plan)
    fallback_key = cache_identity(request, plan)
    if cache is not None and request.cache_policy in {"read_through", "cache_only"}:
        try:
            cached=cache.find(lookup_key)
            cached_release = cached.get("observed_source_release") or request.requested_source_release
            cached_state = cached.get("release_verification_state")
            if (cached.get("cache_lookup_identity") != lookup_key
                    or cached.get("planning_query_plan_id") != plan.plan_id
                    or cached.get("cache_identity") != cache_identity(request, plan, cached_release, cached_state)):
                raise ValueError("cache_identity_mismatch")
            # Passing no cache prevents recursive reads while preserving the
            # caller's immutable request identity in reconstructed records.
            result=fetch_opentargets(request, FakeOpenTargetsTransport(_cached_responses(cached)), None)
            return _with_origin(result, "cache_only_retrieval" if request.cache_policy == "cache_only" else "valid_cache_hit")
        except ValueError:
            if request.cache_policy == "cache_only":
                empty=OpenTargetsCoverageReport(request.request_id, request.query_type, {})
                return OpenTargetsFetchResult(
                    "cache_error", request, plan, fallback_key, "not_reported", (), (),
                    empty, ("cache_only_miss",), "cache_only_retrieval",
                )
    responses=[]; records=[]; resolutions=[]; execution_operations=[]
    if request.query_type == "association_ranked":
        errors=[]; terminated=False; expected_total=None; source_target_ids=set()
        for operation in plan.operations:
            execution_operations.append(operation)
            try: response=transport.execute(operation["operation_id"],operation["document"],operation["variables"],request.timeout_seconds)
            except Exception: return _result(request,plan,"transport_error",(),(),{},responses,("transport_error",),execution_operations)
            responses.append(response)
            if _response_bad(response) or response.payload.get("errors"): return _result(request,plan,"response_error",(),records,{},responses,("graphql_or_http_error",),execution_operations)
            payload_data=response.payload.get("data")
            disease=payload_data.get("disease") if isinstance(payload_data, Mapping) else None
            if not isinstance(disease,Mapping): return _result(request,plan,"response_error",(),records,{},responses,("missing_disease",),execution_operations)
            assoc=disease.get("associatedTargets")
            if not isinstance(assoc, Mapping): return _result(request,plan,"response_error",(),records,{},responses,("malformed_associated_targets",),execution_operations)
            rows=assoc.get("rows",[])
            if not isinstance(rows,(list,tuple)): return _result(request,plan,"response_error",(),records,{},responses,("malformed_rows",),execution_operations)
            expected_total=assoc.get("count",expected_total)
            release,state=_release(request,responses)
            for row in rows:
                target=row.get("target") if isinstance(row,Mapping) else None
                if not isinstance(target,Mapping): continue
                source_target_id=target.get("id")
                if not isinstance(source_target_id, str) or source_target_id in source_target_ids:
                    return _result(request,plan,"response_error",(),(),{},responses,("duplicate_source_record",),execution_operations)
                source_target_ids.add(source_target_id)
                records.append(_record(request,target,response,release,state,disease.get("id"),{"score":row.get("score"),"association_order":len(records),"datatypeScores":row.get("datatypeScores"),"datasourceScores":row.get("datasourceScores")}))
            if not rows or (isinstance(expected_total,int) and len(records)>=expected_total): terminated=True; break
        result=_result(request,plan,"completed" if terminated else "truncated",(),records,{},responses,execution_operations=execution_operations)
        return _store_if_needed(request, plan, cache, responses, result)
    categories={"resolved_and_retrieved":[],"resolved_no_record":[],"unresolved":[],"ambiguous":[],"invalid":[],"retrieval_failed":[]}
    for target_id in request.target_universe:
        if request.target_identifier_type=="ensembl_gene_id":
            if not target_id.startswith("ENSG") or len(target_id)!=15 or not target_id[4:].isdigit():
                resolutions.append(OpenTargetsTargetResolution(target_id,"ensembl_gene_id","invalid_identifier")); categories["invalid"].append(target_id); continue
            resolution=OpenTargetsTargetResolution(target_id,"ensembl_gene_id","resolved_exact",ensembl_gene_id=target_id)
        else:
            op=next(o for o in plan.operations if o["operation_id"]=="resolve_"+target_id)
            execution_operations.append(op)
            try: response=transport.execute(op["operation_id"],op["document"],op["variables"],request.timeout_seconds)
            except Exception:
                resolutions.append(OpenTargetsTargetResolution(target_id,"gene_symbol","retrieval_failed",error_codes=("transport_error",))); categories["retrieval_failed"].append(target_id); continue
            responses.append(response)
            if _response_bad(response) or response.payload.get("errors"):
                resolutions.append(OpenTargetsTargetResolution(target_id,"gene_symbol","retrieval_failed",error_codes=("resolution_response_error",))); categories["retrieval_failed"].append(target_id); continue
            payload_data=response.payload.get("data")
            search=payload_data.get("search") if isinstance(payload_data, Mapping) else None
            if not isinstance(search, Mapping):
                resolutions.append(OpenTargetsTargetResolution(target_id,"gene_symbol","retrieval_failed",error_codes=("malformed_resolution_search",))); categories["retrieval_failed"].append(target_id); continue
            hits=search.get("hits",())
            if not isinstance(hits, (list, tuple)):
                resolutions.append(OpenTargetsTargetResolution(target_id,"gene_symbol","retrieval_failed",error_codes=("malformed_resolution_hits",))); categories["retrieval_failed"].append(target_id); continue
            candidate_ids=sorted({h.get("id") for h in hits if isinstance(h,Mapping) and h.get("entity")=="TARGET" and isinstance(h.get("id"),str) and h["id"].startswith("ENSG")})
            exact=[]; candidate_failed=False
            for ensembl in candidate_ids:
                candidate_operation="target_candidate_"+target_id+"_"+ensembl
                execution_operations.append({"operation_id":candidate_operation,"document":"target","variables":{"ensemblId":ensembl}})
                try:
                    candidate_response=transport.execute(candidate_operation,"target",{"ensemblId":ensembl},request.timeout_seconds)
                except Exception:
                    candidate_failed=True; continue
                responses.append(candidate_response)
                if _response_bad(candidate_response) or candidate_response.payload.get("errors"):
                    candidate_failed=True
                    continue
                candidate_target=_target(candidate_response.payload)
                if isinstance(candidate_target, Mapping) and candidate_target.get("approvedSymbol")==target_id:
                    exact.append((ensembl, candidate_target, candidate_response))
            # Every discovered candidate must be validated before an exact
            # symbol resolution can be trusted.  A failed candidate might be
            # another exact approved-symbol match, so accepting a surviving
            # match would silently mask an unresolved ambiguity.
            if candidate_failed:
                resolutions.append(OpenTargetsTargetResolution(target_id,"gene_symbol","retrieval_failed",error_codes=("candidate_validation_transport_error",))); categories["retrieval_failed"].append(target_id); continue
            if not exact:
                resolutions.append(OpenTargetsTargetResolution(target_id,"gene_symbol","unresolved")); categories["unresolved"].append(target_id); continue
            if len(exact)>1:
                resolutions.append(OpenTargetsTargetResolution(target_id,"gene_symbol","ambiguous",candidates=tuple({"ensembl_gene_id": item[0], "approved_symbol": item[1].get("approvedSymbol")} for item in exact))); categories["ambiguous"].append(target_id); continue
            ensembl, resolved_target, resolved_response=exact[0]
            resolution=OpenTargetsTargetResolution(target_id,"gene_symbol","resolved_exact",approved_symbol=target_id,ensembl_gene_id=ensembl,approved_name=resolved_target.get("approvedName"),source_record_provenance={"operation_id":resolved_response.operation_id})
            resolutions.append(resolution)
            release,state=_release(request,responses); records.append(_record(request,resolved_target,resolved_response,release,state,request.disease_id)); categories["resolved_and_retrieved"].append(target_id)
            continue
        resolutions.append(resolution)
        execution_operations.append({"operation_id":"target_"+resolution.ensembl_gene_id,"document":"target","variables":{"ensemblId":resolution.ensembl_gene_id}})
        try: response=transport.execute("target_"+resolution.ensembl_gene_id,"target",{"ensemblId":resolution.ensembl_gene_id},request.timeout_seconds)
        except Exception: categories["retrieval_failed"].append(target_id); continue
        responses.append(response)
        if _response_bad(response) or response.payload.get("errors"):
            categories["retrieval_failed"].append(target_id); continue
        target=_target(response.payload)
        if not isinstance(target,Mapping): categories["resolved_no_record"].append(target_id); continue
        release,state=_release(request,responses); records.append(_record(request,target,response,release,state,request.disease_id)); categories["resolved_and_retrieved"].append(target_id)
    status="completed" if not any(categories[k] for k in ("unresolved","ambiguous","invalid","retrieval_failed","resolved_no_record")) else "completed_with_gaps"
    result=_result(request,plan,status,resolutions,records,categories,responses,execution_operations=execution_operations)
    return _store_if_needed(request, plan, cache, responses, result)

def _store_if_needed(request, planning_plan, cache, responses, result):
    if cache is not None and request.cache_policy in {"read_through", "refresh"}:
        observed_release = next((response.source_release for response in responses if response.source_release), None)
        cache.write(result.cache_identity, {
            "cache_identity": result.cache_identity,
            "cache_lookup_identity": cache_lookup_identity(request, planning_plan),
            "request_identity": request.request_id,
            "query_plan_id": result.query_plan.plan_id,
            "planning_query_plan_id": planning_plan.plan_id,
            "requested_source_release": request.requested_source_release,
            "observed_source_release": observed_release,
            "release_verification_state": result.release_verification_state,
            "query_type": request.query_type,
            "target_universe_hash": request.target_universe_hash,
            "result_id": result.result_id,
            "responses": [
                {"operation_id": r.operation_id, "status_code": r.status_code, "payload": r.payload,
                 "payload_sha256": r.payload_sha256, "source_release": r.source_release,
                 "error_codes": list(r.error_codes), "retry_count": r.retry_count}
                for r in responses
            ],
        })
        return _with_origin(result, "refreshed_cache" if request.cache_policy == "refresh" else "live_transport")
    return result
