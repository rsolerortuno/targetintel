import pytest

from targetintel.feasibility.opentargets_models import OpenTargetsTransportResponse
from targetintel.feasibility.opentargets_transport import FakeOpenTargetsTransport


def test_transport_response_rejects_malformed_json_and_fake_transport_is_injected() -> None:
    with pytest.raises(ValueError, match="malformed JSON"):
        OpenTargetsTransportResponse("operation", 200, [])
    response = OpenTargetsTransportResponse("operation", 200, {"data": {}})
    fake = FakeOpenTargetsTransport({"operation": response})
    assert fake.execute("operation", "target", {}, 1).payload_sha256 == response.payload_sha256
    assert fake.calls == [("operation", "target", {})]
