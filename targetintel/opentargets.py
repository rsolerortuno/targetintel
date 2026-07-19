"""
Open Targets ingestion utilities for TargetIntel-IO.

This module retrieves melanoma-associated targets from the Open Targets
Platform GraphQL API and caches the raw response locally.

The goal of this module is to provide the baseline disease-association layer.
TargetIntel-IO then adds resistance-axis annotation, role classification,
modality reasoning, and therapeutic-intent-aware ranking on top.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import requests

from targetintel.cache import get_or_fetch_json


OPEN_TARGETS_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"

# MONDO_0005105 is melanoma in the Open Targets / MONDO disease ontology.
DEFAULT_MELANOMA_DISEASE_ID = "MONDO_0005105"

DEFAULT_CACHE_PATH = Path("data/cache/opentargets_melanoma_targets.json")


ASSOCIATED_TARGETS_QUERY = """
query associatedTargets($efoId: String!, $index: Int!, $size: Int!) {
  disease(efoId: $efoId) {
    id
    name
    associatedTargets(
      page: { index: $index, size: $size }
      orderByScore: "score desc"
    ) {
      count
      rows {
        score
        datatypeScores {
          id
          score
        }
        datasourceScores {
          id
          score
        }
        target {
          id
          approvedSymbol
          approvedName
          biotype
        }
      }
    }
  }
}
"""


def run_graphql_query(
    query: str,
    variables: dict[str, Any],
    url: str = OPEN_TARGETS_GRAPHQL_URL,
    timeout: int = 60,
) -> dict[str, Any]:
    """
    Run a GraphQL query against the Open Targets Platform API.

    Raises an informative error containing the HTTP response body when the
    request or GraphQL query fails.
    """
    status_code, payload, response_text, _headers = post_graphql_payload(
        query=query,
        variables=variables,
        url=url,
        timeout=timeout,
    )

    # Preserve the legacy `requests.Response.ok` success boundary.  The
    # existing helper follows redirects by default, but injected callers may
    # still return a 3xx response and historically received its valid payload.
    if status_code >= 400:
        response_body = (
            payload
            if payload is not None
            else response_text[:5000]
        )

        raise RuntimeError(
            "Open Targets request failed.\n"
            f"HTTP status: {status_code}\n"
            f"URL: {url}\n"
            f"Variables: {variables}\n"
            f"Response: {response_body}"
        )

    if not isinstance(payload, dict):
        raise ValueError(
            "Open Targets returned a non-JSON or invalid JSON response."
        )

    if payload.get("errors"):
        raise RuntimeError(
            "Open Targets GraphQL query failed.\n"
            f"Variables: {variables}\n"
            f"Errors: {payload['errors']}"
        )

    data = payload.get("data")

    if not isinstance(data, dict):
        raise ValueError(
            "Open Targets returned no valid GraphQL data object.\n"
            f"Response: {payload}"
        )

    return data


def post_graphql_payload(
    query: str,
    variables: dict[str, Any],
    url: str = OPEN_TARGETS_GRAPHQL_URL,
    timeout: int = 60,
    *,
    allow_redirects: bool = True,
) -> tuple[int, dict[str, Any] | None, str, dict[str, str]]:
    """Execute the shared low-level GraphQL HTTP operation.

    The legacy helper keeps its historical redirect behaviour.  New ingestion
    code passes the official endpoint and disables redirects explicitly.
    """
    response = requests.post(
        url,
        json={"query": query, "variables": variables},
        timeout=timeout,
        allow_redirects=allow_redirects,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, response.text, dict(response.headers)


def fetch_associated_targets_page(
    disease_id: str,
    index: int = 0,
    size: int = 100,
) -> dict[str, Any]:
    """
    Fetch one page of disease-associated targets from Open Targets.
    """
    variables = {
        "efoId": disease_id,
        "index": index,
        "size": size,
    }

    return run_graphql_query(
        query=ASSOCIATED_TARGETS_QUERY,
        variables=variables,
    )


def fetch_associated_targets(
    disease_id: str = DEFAULT_MELANOMA_DISEASE_ID,
    page_size: int = 100,
    max_pages: int = 3,
) -> dict[str, Any]:
    """
    Fetch associated targets for a disease from Open Targets.

    Parameters
    ----------
    disease_id:
        Disease MONDO ID.
    page_size:
        Number of targets per page.
    max_pages:
        Maximum number of pages to fetch. For the MVP, keep this conservative.

    Returns
    -------
    dict
        Raw Open Targets disease object with associated target rows.
    """
    all_rows: list[dict[str, Any]] = []
    disease_info: dict[str, Any] | None = None
    total_count: int | None = None

    for page_index in range(max_pages):
        data = fetch_associated_targets_page(
            disease_id=disease_id,
            index=page_index,
            size=page_size,
        )

        disease = data.get("disease")

        if disease is None:
            raise ValueError(f"No disease returned for MONDO ID: {disease_id}")

        associated_targets = disease["associatedTargets"]

        if disease_info is None:
            disease_info = {
                "id": disease["id"],
                "name": disease["name"],
            }
            total_count = associated_targets["count"]

        rows = associated_targets.get("rows", [])
        all_rows.extend(rows)

        if len(all_rows) >= associated_targets["count"]:
            break

        if not rows:
            break

    return {
        "disease": disease_info,
        "associatedTargets": {
            "count": total_count,
            "rows": all_rows,
        },
    }


def fetch_associated_targets_cached(
    disease_id: str = DEFAULT_MELANOMA_DISEASE_ID,
    page_size: int = 100,
    max_pages: int = 3,
    cache_path: str | Path = DEFAULT_CACHE_PATH,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch associated targets using local JSON cache.
    """
    return get_or_fetch_json(
        cache_path=cache_path,
        fetch_fn=lambda: fetch_associated_targets(
            disease_id=disease_id,
            page_size=page_size,
            max_pages=max_pages,
        ),
        refresh=refresh,
        source="Open Targets Platform GraphQL API",
        metadata={
            "disease_id": disease_id,
            "page_size": page_size,
            "max_pages": max_pages,
        },
    )


def scored_components_to_dict(
    components: list[dict[str, Any]] | None,
) -> dict[str, float]:
    """
    Convert Open Targets scored components into a compact dictionary.
    """
    if not components:
        return {}

    return {
        component["id"]: component["score"]
        for component in components
        if component.get("id") is not None
    }


def associated_targets_to_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    """
    Convert raw Open Targets associated target payload into a dataframe.
    """
    disease = payload["disease"]
    rows = payload["associatedTargets"]["rows"]

    records: list[dict[str, Any]] = []

    for row in rows:
        target = row.get("target", {})

        records.append(
            {
                "target_id": target.get("id"),
                "target_symbol": target.get("approvedSymbol"),
                "target_name": target.get("approvedName"),
                "biotype": target.get("biotype"),
                "disease_id": disease.get("id"),
                "disease_name": disease.get("name"),
                "opentargets_score": row.get("score"),
                "datatype_scores": scored_components_to_dict(
                    row.get("datatypeScores")
                ),
                "datasource_scores": scored_components_to_dict(
                    row.get("datasourceScores")
                ),
            }
        )

    df = pd.DataFrame(records)

    if not df.empty:
        df = df.sort_values(
            by="opentargets_score",
            ascending=False,
        ).reset_index(drop=True)

    return df


def get_melanoma_associated_targets(
    page_size: int = 100,
    max_pages: int = 3,
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Fetch melanoma-associated targets from Open Targets and return a dataframe.
    """
    payload = fetch_associated_targets_cached(
        disease_id=DEFAULT_MELANOMA_DISEASE_ID,
        page_size=page_size,
        max_pages=max_pages,
        refresh=refresh,
    )

    return associated_targets_to_dataframe(payload)
