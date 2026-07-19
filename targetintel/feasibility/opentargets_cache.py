"""Explicit atomic cache for complete immutable fetch results."""
from __future__ import annotations
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
import json, os, tempfile
from .opentargets_models import OpenTargetsFetchRequest, OpenTargetsQueryPlan, canonical_json


def _cache_identity_payload(request: OpenTargetsFetchRequest, plan: OpenTargetsQueryPlan) -> dict:
    """Return the release-independent part of a cache identity.

    Observed release metadata is unavailable until after a live transport call.
    It therefore cannot be guessed for cache lookup; it remains in the
    release-aware physical key returned by :func:`cache_identity`.
    """
    return {"cache_schema_version":"v1","requested_source_release":request.requested_source_release,"endpoint_identity":request.endpoint_identity,"query_type":request.query_type,"query_schema_version":request.query_schema_version,"disease_id":request.disease_id,"association_scope":request.association_scope,"page_size":request.page_size,"max_pages":request.max_pages,"target_identifier_type":request.target_identifier_type,"target_universe_hash":request.target_universe_hash,"query_document_hash":plan.query_document_hash}


def cache_lookup_identity(request: OpenTargetsFetchRequest, plan: OpenTargetsQueryPlan) -> str:
    """Identify compatible cache manifests before source release is observed."""
    return sha256(canonical_json(_cache_identity_payload(request, plan)).encode()).hexdigest()


def cache_identity(request: OpenTargetsFetchRequest, plan: OpenTargetsQueryPlan, observed_release: str | None = None, verification_state: str = "not_reported") -> str:
    # Observed release metadata is source provenance, even when it cannot be
    # verified against a caller-pinned release.  Retaining it prevents cache
    # reuse across distinct observed source releases.
    payload={**_cache_identity_payload(request, plan),"observed_source_release":observed_release,"release_verification_state":verification_state}
    return sha256(canonical_json(payload).encode()).hexdigest()
class OpenTargetsCache:
    def __init__(self, root: str | Path): self.root=Path(root)
    def _path(self,key): return self.root / (key + ".json")
    def write(self,key: str, value: dict) -> None:
        self.root.mkdir(parents=True,exist_ok=True)
        content=canonical_json(value)
        envelope={
            "payload": value,
            "payload_sha256": sha256(content.encode()).hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }; fd,name=tempfile.mkstemp(prefix=".ot-",dir=self.root); os.close(fd)
        try:
            Path(name).write_text(canonical_json(envelope),encoding="utf-8"); os.replace(name,self._path(key))
        finally:
            if Path(name).exists(): Path(name).unlink()
    def read(self,key: str) -> dict:
        try: envelope=json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc: raise ValueError("cache_miss_or_corrupt") from exc
        if not isinstance(envelope,dict) or set(envelope)!={"payload","payload_sha256","created_at"} or not isinstance(envelope["created_at"],str) or sha256(canonical_json(envelope["payload"]).encode()).hexdigest()!=envelope["payload_sha256"]: raise ValueError("corrupt_cache")
        return envelope["payload"]

    def find(self, lookup_identity: str) -> dict:
        """Return one exact compatible manifest, failing closed on ambiguity."""
        matches = []
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError as exc:
            raise ValueError("cache_miss_or_corrupt") from exc
        for path in paths:
            value = self.read(path.stem)
            if value.get("cache_lookup_identity") == lookup_identity:
                matches.append(value)
        if len(matches) != 1:
            raise ValueError("cache_miss_or_ambiguous")
        return matches[0]
