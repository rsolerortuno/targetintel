import requests
import pandas as pd


OPENTARGETS_GRAPHQL_URL = "https://api.platform.opentargets.org/api/v4/graphql"


def run_graphql_query(query: str, variables: dict) -> dict:
    """
    Run a GraphQL query against the Open Targets Platform API.

    If the query fails, print the API response so the error is easier to debug.
    """
    response = requests.post(
        OPENTARGETS_GRAPHQL_URL,
        json={"query": query, "variables": variables},
        timeout=30,
    )

    if response.status_code != 200:
        print("\nOpen Targets API error")
        print("----------------------")
        print(f"Status code: {response.status_code}")
        print(response.text)
        response.raise_for_status()

    data = response.json()

    if "errors" in data:
        print("\nGraphQL errors")
        print("--------------")
        for error in data["errors"]:
            print(error)
        raise RuntimeError("Open Targets GraphQL query failed.")

    return data


def search_disease(query: str, size: int = 10) -> pd.DataFrame:
    """
    Search Open Targets for diseases matching a query.

    Example:
        search_disease("melanoma")
    """
    graphql_query = """
    query SearchDisease(
      $queryString: String!
      $index: Int!
      $size: Int!
      $entityNames: [String!]!
    ) {
      search(
        queryString: $queryString
        entityNames: $entityNames
        page: {index: $index, size: $size}
      ) {
        total
        hits {
          id
          entity
          object {
            ... on Disease {
              id
              name
              description
            }
          }
        }
      }
    }
    """

    variables = {
        "queryString": query,
        "index": 0,
        "size": size,
        "entityNames": ["Disease"],
    }

    data = run_graphql_query(graphql_query, variables)
    hits = data["data"]["search"]["hits"]

    records = []

    for hit in hits:
        disease_obj = hit.get("object")

        if disease_obj is None:
            continue

        records.append(
            {
                "id": disease_obj.get("id"),
                "name": disease_obj.get("name"),
                "description": disease_obj.get("description"),
            }
        )

    return pd.DataFrame(records)


def get_associated_targets(disease_id: str, size: int = 100) -> pd.DataFrame:
    """
    Get associated targets for an Open Targets disease ID.

    Example:
        get_associated_targets("EFO_0000756", size=100)
    """
    graphql_query = """
    query AssociatedTargets(
      $diseaseId: String!
      $index: Int!
      $size: Int!
    ) {
      disease(efoId: $diseaseId) {
        id
        name
        associatedTargets(page: {index: $index, size: $size}) {
          count
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
        "index": 0,
        "size": size,
    }

    data = run_graphql_query(graphql_query, variables)
    disease_data = data["data"]["disease"]

    if disease_data is None:
        raise ValueError(f"No disease found for disease_id: {disease_id}")

    rows = disease_data["associatedTargets"]["rows"]

    records = []

    for row in rows:
        target = row["target"]

        records.append(
            {
                "disease_id": disease_data["id"],
                "disease_name": disease_data["name"],
                "target_id": target["id"],
                "target_symbol": target["approvedSymbol"],
                "target_name": target["approvedName"],
                "biotype": target["biotype"],
                "opentargets_score": row["score"],
            }
        )

    return pd.DataFrame(records)
