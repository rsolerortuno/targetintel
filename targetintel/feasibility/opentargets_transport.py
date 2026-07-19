"""Small injectable transport boundary; no arbitrary URL fetcher is exposed."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Protocol, Mapping, Any

from targetintel.opentargets import post_graphql_payload
from .opentargets_models import OpenTargetsTransportResponse, OFFICIAL_GRAPHQL_ENDPOINT
from .opentargets_queries import ASSOCIATION_QUERY, RESOLUTION_QUERY, TARGET_QUERY

class OpenTargetsTransport(Protocol):
    def execute(self, operation_id: str, document: str, variables: Mapping[str, Any], timeout_seconds: int) -> OpenTargetsTransportResponse: ...
class LiveOpenTargetsTransport:
    """Official endpoint only. Callers cannot supply an endpoint or headers."""
    _docs={"association":ASSOCIATION_QUERY,"resolution":RESOLUTION_QUERY,"target":TARGET_QUERY}
    def execute(self, operation_id, document, variables, timeout_seconds):
        if document not in self._docs:
            raise ValueError("unknown_project_operation")
        status, payload, _text, headers = post_graphql_payload(
            query=self._docs[document], variables=dict(variables),
            url=OFFICIAL_GRAPHQL_ENDPOINT, timeout=timeout_seconds,
            allow_redirects=False,
        )
        if not isinstance(payload, dict):
            raise ValueError("malformed_json")
        return OpenTargetsTransportResponse(
            operation_id=operation_id, status_code=status, payload=payload,
            source_release=headers.get("x-opentargets-release"),
            retrieval_timestamp=datetime.now(timezone.utc),
        )
class FakeOpenTargetsTransport:
    """Deterministic test double keyed by operation id."""
    def __init__(self, responses: Mapping[str, OpenTargetsTransportResponse | Exception]): self.responses=dict(responses); self.calls=[]
    def execute(self, operation_id, document, variables, timeout_seconds):
        self.calls.append((operation_id,document,dict(variables)))
        value=self.responses.get(operation_id)
        if value is None: raise RuntimeError("missing_fake_response")
        if isinstance(value,Exception): raise value
        return value
