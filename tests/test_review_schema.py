import pytest
from targetintel.llm.review_schema import REVIEW_SCHEMA_ID, REVIEW_SCHEMA_VERSION, reject_unsafe

def test_schema_is_stable_and_rejects_hidden_reasoning_and_secrets():
    assert (REVIEW_SCHEMA_ID, REVIEW_SCHEMA_VERSION) == ("targetintel-human-review-decision", "v1")
    for value in ({"thinking":"x"}, {"nested":{"reasoning":"x"}}, {"token":"x"}):
        with pytest.raises(ValueError): reject_unsafe(value)
