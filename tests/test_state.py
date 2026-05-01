from datetime import datetime
from pods.state.schema import PodState, Pod, Member, Key, UsageRecord


def test_pod_has_uuid_id():
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    assert pod.id
    assert len(pod.id) == 36  # UUID format


def test_schema_roundtrip():
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    member = Member(name="node1", tailscale_ip="100.1.2.3", role="coordinator", os="linux")
    key = Key(key="pk_abc123", label="test-key")
    state = PodState(pod=pod, members=[member], keys=[key])

    data = state.model_dump_json()
    restored = PodState.model_validate_json(data)

    assert restored.pod.name == "test"
    assert restored.members[0].tailscale_ip == "100.1.2.3"
    assert restored.keys[0].key == "pk_abc123"


def test_member_defaults():
    m = Member(name="box1", tailscale_ip="100.1.1.1", role="worker", os="linux")
    assert m.connection_type == "relay"
    assert m.models == []
    assert m.gpu_vram_gb == 0
    assert m.inference_engine == "none"


def test_usage_record_fields():
    rec = UsageRecord(
        key="pk_x", model="qwen32b",
        prompt_tokens=10, completion_tokens=20,
        backend="llamacpp", latency_ms=150,
    )
    assert rec.backend == "llamacpp"
    assert isinstance(rec.timestamp, datetime)


from pods.state.defaults import new_pod, new_member, new_key


def test_new_key_format():
    key = new_key("my-label")
    assert key.key.startswith("pk_")
    assert len(key.key) == 35  # "pk_" + 32 chars
    assert key.label == "my-label"
    assert key.total_requests == 0
    assert key.total_tokens == 0


def test_new_key_is_unique():
    k1 = new_key("a")
    k2 = new_key("b")
    assert k1.key != k2.key


def test_new_member_defaults():
    m = new_member("box1", "100.1.1.1", "coordinator", "linux", gpu_vram_gb=8)
    assert m.role == "coordinator"
    assert m.connection_type == "relay"
    assert m.models == []
    assert m.gpu_vram_gb == 8


def test_new_pod_fields():
    p = new_pod("mypod", "100.1.2.3")
    assert p.name == "mypod"
    assert p.coordinator_ip == "100.1.2.3"
    assert p.id  # UUID generated


import pytest
from pods.state.store import StateStore
from pods.errors import StateError


def test_store_load_missing_file(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    with pytest.raises(StateError, match="not found"):
        store.load()


def test_store_load_malformed_json(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{invalid json")
    store = StateStore(path=p)
    with pytest.raises(StateError, match="malformed"):
        store.load()


def test_store_save_and_load(tmp_path):
    pod = Pod(name="mypod", coordinator_ip="100.2.3.4")
    state = PodState(pod=pod)
    store = StateStore(path=tmp_path / "state.json")
    store.save(state)
    loaded = store.load()
    assert loaded.pod.name == "mypod"
    assert loaded.pod.coordinator_ip == "100.2.3.4"


def test_store_atomic_write_no_tmp_leftover(tmp_path):
    pod = Pod(name="mypod", coordinator_ip="100.2.3.4")
    state = PodState(pod=pod)
    store = StateStore(path=tmp_path / "state.json")
    store.save(state)
    assert not (tmp_path / "state.json.tmp").exists()


def test_store_save_creates_parent_dir(tmp_path):
    nested = tmp_path / "deep" / "path" / "state.json"
    pod = Pod(name="mypod", coordinator_ip="100.2.3.4")
    state = PodState(pod=pod)
    store = StateStore(path=nested)
    store.save(state)
    assert nested.exists()


def test_trim_usage_keeps_last_1000(tmp_path):
    from pods.state.schema import UsageRecord
    pod = Pod(name="mypod", coordinator_ip="100.2.3.4")
    records = [
        UsageRecord(
            key="pk_x", model="m",
            prompt_tokens=1, completion_tokens=1,
            backend="llamacpp", latency_ms=100,
        )
        for _ in range(1100)
    ]
    state = PodState(pod=pod, usage=records)
    store = StateStore(path=tmp_path / "state.json")
    trimmed = store.trim_usage(state)
    assert len(trimmed.usage) == 1000


def test_trim_usage_under_limit_unchanged(tmp_path):
    from pods.state.schema import UsageRecord
    pod = Pod(name="mypod", coordinator_ip="100.2.3.4")
    records = [
        UsageRecord(
            key="pk_x", model="m",
            prompt_tokens=1, completion_tokens=1,
            backend="llamacpp", latency_ms=100,
        )
        for _ in range(50)
    ]
    state = PodState(pod=pod, usage=records)
    store = StateStore(path=tmp_path / "state.json")
    trimmed = store.trim_usage(state)
    assert len(trimmed.usage) == 50
