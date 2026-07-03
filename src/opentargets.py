import requests
import pandas as pd


OPENTARGETS_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"


def search_disease(query: str, size: int = 10) -> pd.DataFrame:
    """
    Search Open Targets for diseases matching a query.
    """
    graphql_query = """
    query SearchDisease($queryString: String!, $size: Int!) {
      search(queryString: $queryString, entityNames: ["disease"], size: $size) {
        hits {
          id
          name
          entity
          description
        }
      }
    }
    """

    variables = {
        "queryString": query,
        "size": size,
    }

    response = requests.post(
        OPENTARGETS_GRAPHQL_URL,
        json={"query": graphql_query, "variables": variables},
        timeout=30,
    )
    response.raise_for_status()

    hits = response.json()["data"]["search"]["hits"]
    return pd.DataFrame(hits)


def get_associated_targets(disease_id: str, size: int = 100) -> pd.DataFrame:
    """
    Get associated targets for an Open Targets disease ID.
    """
    graphql_query = """
    query AssociatedTargets($diseaseId: String!, $size: Int!) {
      disease(efoId: $diseaseId) {
        id
        name
        associatedTargets(page: {index: 0, size: $size}) {
          rows {
            score
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

    variables = {
        "diseaseId": disease_id,
        "size": size,
    }

    response = requests.post(
        OPENTARGETS_GRAPHQL_URL,
        json={"query": graphql_query, "variables": variables},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()["data"]["disease"]
    rows = data["associatedTargets"]["rows"]

    records = []
    for row in rows:
        target = row["target"]
        records.append(
            {
                "disease_id": data["id"],
                "disease_name": data["name"],
                "target_id": target["id"],
                "target_symbol": target["approvedSymbol"],
                "target_name": target["approvedName"],
                "biotype": target["biotype"],
                "opentargets_score": row["score"],
            }
        )

    return pd.DataFrame(records)
