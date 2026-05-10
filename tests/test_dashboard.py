from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from pods.gateway.app import app
from pods.gateway.dashboard import get_store
from pods.state.defaults import new_raw_key
from pods.state.schema import Member, Model, Pod, PodState, UsageRecord
from pods.state.store import StateStore


def _state(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    now = datetime.now(timezone.utc)
    coord = Member(
        node_id="coord-id", name="coordinator", tailscale_ip="100.0.0.1",
        role="coordinator", os="linux", gpu_vram_gb=24, last_seen=now,
    )
    worker_ok = Member(
        node_id="w1-id", name="w1", tailscale_ip="100.0.0.2",
        role="worker", os="linux", gpu_vram_gb=12, last_seen=now,
    )
    worker_dead = Member(
        node_id="w2-id", name="w2", tailscale_ip="100.0.0.3",
        role="worker", os="linux", last_seen=now - timedelta(seconds=999),
    )
    model = Model(
        name="qwen0.5b", file="qwen.gguf", size_gb=0.4, loaded=True,
        worker_nodes=["100.0.0.2:50052"],
    )
    _, key = new_raw_key("demo")
    key.total_requests = 7
    key.total_tokens = 1234
    usage = UsageRecord(
        key_id=key.key_id, model="qwen0.5b",
        prompt_tokens=10, completion_tokens=20, backend="llamacpp", latency_ms=150,
    )
    state = PodState(
        pod=Pod(name="demo-pod", coordinator_ip="100.0.0.1"),
        members=[coord, worker_ok, worker_dead],
        models=[model],
        keys=[key],
        usage=[usage],
    )
    store.save(state)
    return store


def test_dashboard_html_served():
    client = TestClient(app)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Pods Dashboard" in r.text
    assert "/dashboard/state" in r.text  # JS fetch URL


def test_dashboard_state_returns_full_payload(tmp_path, monkeypatch):
    store = _state(tmp_path)
    monkeypatch.setattr("pods.gateway.dashboard.tcp_probe_many", lambda targets, timeout=1.0: {})
    app.dependency_overrides[get_store] = lambda: store

    try:
        client = TestClient(app)
        r = client.get("/dashboard/state")
        assert r.status_code == 200
        data = r.json()
        assert data["pod"]["name"] == "demo-pod"
        assert len(data["members"]) == 3
        labels = {m["name"]: m["label"] for m in data["members"]}
        assert labels["coordinator"] == "OK"
        assert labels["w1"] == "DEGRADED"  # probes return False
        assert labels["w2"] == "DEAD"
        assert data["models"][0]["loaded"] is True
        assert data["models"][0]["worker_nodes"] == ["100.0.0.2:50052"]
        assert data["keys"][0]["label"] == "demo"
        assert "key_hash" not in data["keys"][0]  # secret never leaked
        assert len(data["recent_usage"]) == 1
    finally:
        app.dependency_overrides.clear()


def test_dashboard_state_keys_sanitized(tmp_path, monkeypatch):
    store = _state(tmp_path)
    monkeypatch.setattr("pods.gateway.dashboard.tcp_probe_many", lambda targets, timeout=1.0: {})
    app.dependency_overrides[get_store] = lambda: store

    try:
        client = TestClient(app)
        r = client.get("/dashboard/state")
        assert r.status_code == 200
        body_text = r.text
        # The key_hash field must never appear in the dashboard payload
        assert "key_hash" not in body_text
    finally:
        app.dependency_overrides.clear()
