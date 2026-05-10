from fastapi.testclient import TestClient

from pods.gateway.app import app
from pods.gateway.auth import validate_api_key
from pods.gateway.routes_external import get_store
from pods.state.defaults import new_raw_key
from pods.state.schema import Key, Model, Pod, PodState
from pods.state.store import StateStore


def _setup(tmp_path, *, reloading: bool):
    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="t", coordinator_ip="100.0.0.1")
    raw_key, key = new_raw_key("test")
    model = Model(name="qwen32b", file="qwen32b.gguf", size_gb=20.0, loaded=True, reloading=reloading)
    store.save(PodState(pod=pod, models=[model], keys=[key]))
    return store, raw_key, key


def _client_with(store, key: Key):
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[validate_api_key] = lambda: key
    return TestClient(app)


def test_chat_returns_503_when_reloading(tmp_path):
    store, _, key = _setup(tmp_path, reloading=True)
    try:
        client = _client_with(store, key)
        r = client.post(
            "/v1/chat/completions",
            json={"model": "qwen32b", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer pk_x"},
        )
        assert r.status_code == 503
        assert r.headers.get("Retry-After") == "5"
        assert r.json()["error"] == "model reloading"
    finally:
        app.dependency_overrides.clear()


def test_chat_proceeds_when_not_reloading(tmp_path, monkeypatch):
    store, _, key = _setup(tmp_path, reloading=False)
    # short-circuit select_backend so we don't actually try to call llama-server
    from pods.gateway import routes_external

    async def _fake_stream(url, body):
        from fastapi.responses import StreamingResponse
        async def gen():
            yield "data: [DONE]\n"
        return StreamingResponse(gen(), media_type="text/event-stream"), {
            "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0,
        }

    monkeypatch.setattr(routes_external, "select_backend", lambda m, s: ("llamacpp", "http://x"))
    monkeypatch.setattr(routes_external, "stream_to_backend", _fake_stream)

    try:
        client = _client_with(store, key)
        r = client.post(
            "/v1/chat/completions",
            json={"model": "qwen32b", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer pk_x"},
        )
        assert r.status_code == 200
    finally:
        app.dependency_overrides.clear()
