import json

import pytest

from targetintel.feasibility.opentargets_cache import OpenTargetsCache, cache_identity
from targetintel.feasibility.opentargets_models import OpenTargetsFetchRequest
from targetintel.feasibility.opentargets_queries import build_query_plan


def test_cache_rejects_a_corrupt_entry(tmp_path) -> None:
    cache = OpenTargetsCache(tmp_path)
    cache.write("entry", {"payload": "value"})
    path = tmp_path / "entry.json"
    content = json.loads(path.read_text())
    content["payload_sha256"] = "0" * 64
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="corrupt_cache"):
        cache.read("entry")


def test_pagination_and_universe_change_cache_identity() -> None:
    one = OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105", page_size=100, max_pages=1)
    two = OpenTargetsFetchRequest(query_type="association_ranked", disease_id="MONDO_0005105", page_size=200, max_pages=1)
    directed = OpenTargetsFetchRequest(query_type="directed_target_universe", target_universe=["BRAF"])
    assert cache_identity(one, build_query_plan(one)) != cache_identity(two, build_query_plan(two))
    assert cache_identity(one, build_query_plan(one)) != cache_identity(directed, build_query_plan(directed))
