import base64
import json
import pytest
from pods.network.invite import encode_invite, decode_invite
from pods.errors import NetworkError


def test_encode_decode_roundtrip():
    link = encode_invite("100.1.2.3", "tskey-abc123", "mypod")
    decoded = decode_invite(link)
    assert decoded["coordinator_ip"] == "100.1.2.3"
    assert decoded["authkey"] == "tskey-abc123"
    assert decoded["pod_name"] == "mypod"


def test_encoded_link_is_url_safe():
    link = encode_invite("100.1.2.3", "tskey-abc123", "mypod")
    assert "+" not in link
    assert "/" not in link


def test_decode_invalid_base64():
    with pytest.raises(NetworkError, match="Invalid invite link"):
        decode_invite("not!!!valid")


def test_decode_missing_fields():
    bad = base64.urlsafe_b64encode(
        json.dumps({"coordinator_ip": "100.1.2.3"}).encode()
    ).decode()
    with pytest.raises(NetworkError, match="Invalid invite link"):
        decode_invite(bad)


def test_decode_valid_json_but_wrong_type():
    bad = base64.urlsafe_b64encode(b"[]").decode()
    with pytest.raises(NetworkError, match="Invalid invite link"):
        decode_invite(bad)
