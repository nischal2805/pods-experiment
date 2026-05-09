import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from pods.gateway.auth import validate_api_key
from pods.state.defaults import new_raw_key
from pods.state.schema import Key, PodState, Pod
from pods.state.store import StateStore


def _make_credentials(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_valid_key_returns_key(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    raw_key, key = new_raw_key("test")
    store.save(PodState(pod=pod, keys=[key]))

    result = validate_api_key(credentials=_make_credentials(raw_key), store=store)
    assert result.key_id == key.key_id


def test_invalid_key_raises_401(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    key = Key(key_id="pk_abc123xxxx", key_hash="deadbeef", label="test")
    store.save(PodState(pod=pod, keys=[key]))

    with pytest.raises(HTTPException) as exc:
        validate_api_key(credentials=_make_credentials("pk_wrong"), store=store)
    assert exc.value.status_code == 401


def test_empty_keys_raises_401(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    store.save(PodState(pod=pod))

    with pytest.raises(HTTPException) as exc:
        validate_api_key(credentials=_make_credentials("pk_anything"), store=store)
    assert exc.value.status_code == 401


def test_state_unavailable_raises_503(tmp_path):
    store = StateStore(path=tmp_path / "missing_state.json")

    with pytest.raises(HTTPException) as exc:
        validate_api_key(credentials=_make_credentials("pk_abc"), store=store)
    assert exc.value.status_code == 503
