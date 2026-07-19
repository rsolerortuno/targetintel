"""Versioned, project-owned GraphQL documents and deterministic query plans."""
from __future__ import annotations
from hashlib import sha256
from .opentargets_models import OpenTargetsFetchRequest, OpenTargetsQueryPlan, canonical_json

ASSOCIATION_QUERY = """query AssociatedTargets($efoId:String!,$index:Int!,$size:Int!){disease(efoId:$efoId){id name associatedTargets(page:{index:$index,size:$size} orderByScore:\"score desc\"){count rows{score datatypeScores{id score} datasourceScores{id score} target{id approvedSymbol approvedName biotype}}}}}"""
# Search is only a candidate-discovery operation.  Exact approved-symbol
# validation is performed against TARGET_QUERY's target.approvedSymbol field.
RESOLUTION_QUERY = """query TargetSearch($query:String!){search(queryString:$query){hits{id entity name description}}}"""
TARGET_QUERY = """query Target($ensemblId:String!){target(ensemblId:$ensemblId){id approvedSymbol approvedName biotype tractability{label modality value} safetyLiabilities{event effects datasource} knownDrugs{rows{drug{id name} phase status}}}}"""
def document_hash() -> str: return sha256(canonical_json({"association":ASSOCIATION_QUERY,"resolution":RESOLUTION_QUERY,"target":TARGET_QUERY}).encode()).hexdigest()
def build_query_plan(request: OpenTargetsFetchRequest) -> OpenTargetsQueryPlan:
    """Build only code-owned operations; this function performs no I/O."""
    ops = []
    if request.query_type == "association_ranked":
        for index in range(request.max_pages): ops.append({"operation_id":f"association_page_{index}","document":"association","variables":{"efoId":request.disease_id,"index":index,"size":request.page_size}})
    else:
        for target in request.target_universe:
            if request.target_identifier_type == "gene_symbol":
                ops.append({"operation_id":f"resolve_{target}","document":"resolution","variables":{"query":target}})
            else: ops.append({"operation_id":f"target_{target}","document":"target","variables":{"ensemblId":target}})
    return OpenTargetsQueryPlan(request=request, operations=tuple(ops), query_document_hash=document_hash(), expected_operation_count=len(ops))


def build_execution_query_plan(
    request: OpenTargetsFetchRequest, operations: list[dict] | tuple[dict, ...]
) -> OpenTargetsQueryPlan:
    """Record the exact operations sent during one fetch execution.

    Symbol candidate IDs are source observations and therefore cannot be known
    during the no-I/O request-planning phase.  This separate immutable plan is
    constructed from those code-owned operations after they are selected, so
    its operation list and expected count exactly match transport execution.
    """
    return OpenTargetsQueryPlan(
        request=request,
        operations=tuple(operations),
        query_document_hash=document_hash(),
        expected_operation_count=len(operations),
    )
