from targetintel.llm.grounded_schema import GROUNDED_EXTRACTION_SCHEMA_ID, GROUNDED_EXTRACTION_SCHEMA_VERSION, GroundedSchemaRegistry, grounded_extraction_schema, grounded_schema_canonical_json


def test_grounded_schema_is_stable_closed_and_defensive():
    schema = grounded_extraction_schema()
    assert schema["$id"] == f"{GROUNDED_EXTRACTION_SCHEMA_ID}/{GROUNDED_EXTRACTION_SCHEMA_VERSION}"
    assert schema["additionalProperties"] is False
    assert schema["properties"]["claims"]["items"]["additionalProperties"] is False
    schema["title"] = "changed"
    assert GroundedSchemaRegistry().resolve(GROUNDED_EXTRACTION_SCHEMA_ID, GROUNDED_EXTRACTION_SCHEMA_VERSION)["title"] != "changed"
    assert grounded_schema_canonical_json() == grounded_schema_canonical_json()


def test_schema_registry_fails_closed():
    registry = GroundedSchemaRegistry()
    for identity in (("other", GROUNDED_EXTRACTION_SCHEMA_VERSION), (GROUNDED_EXTRACTION_SCHEMA_ID, "0")):
        try:
            registry.resolve(*identity)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown schema resolved")
