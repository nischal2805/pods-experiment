import os
import signal

import pytest

from pods.errors import InferenceError
from pods.models.manager import ModelManager
from pods.state.schema import Model, Pod, PodState
from pods.state.store import StateStore


def _state(models):
    return PodState(pod=Pod(name="t", coordinator_ip="100.0.0.1"), models=models)


class _StubResp:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


def test_unload_unknown_model(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([]))
    mgr = ModelManager(store=store)
    with pytest.raises(InferenceError, match="not registered"):
        mgr.unload("nope")


def test_unload_not_loaded(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([Model(name="m", file="m.gguf", size_gb=1.0, loaded=False)]))
    mgr = ModelManager(store=store)
    with pytest.raises(InferenceError, match="not loaded"):
        mgr.unload("m")


def test_unload_kills_pid_and_workers(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([
        Model(name="m", file="m.gguf", size_gb=1.0, loaded=True, loaded_pid=12345,
              worker_nodes=["100.0.0.2:50052", "100.0.0.3:50052"]),
    ]))

    killed = []
    def _fake_kill(pid: int, sig):
        killed.append((pid, sig))

    monkeypatch.setattr(os, "kill", _fake_kill)

    posted = []
    def _fake_post(url, **kw):
        posted.append(url)
        return _StubResp(200)

    monkeypatch.setattr("pods.models.manager.httpx.post", _fake_post)

    mgr = ModelManager(store=store)
    result = mgr.unload("m")

    assert killed == [(12345, signal.SIGTERM)]
    assert result["killed_pid"] is True
    assert sorted(result["workers_stopped"]) == ["100.0.0.2", "100.0.0.3"]
    assert "100.0.0.2" in posted[0]

    after = store.load()
    m = after.models[0]
    assert m.loaded is False
    assert m.loaded_pid == 0
    assert m.worker_nodes == []


def test_unload_handles_dead_pid(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([
        Model(name="m", file="m.gguf", size_gb=1.0, loaded=True, loaded_pid=99999, worker_nodes=[]),
    ]))

    def _fake_kill(pid, sig):
        raise ProcessLookupError("no such process")

    monkeypatch.setattr(os, "kill", _fake_kill)

    mgr = ModelManager(store=store)
    result = mgr.unload("m")
    assert result["killed_pid"] is False
    after = store.load()
    assert after.models[0].loaded is False


def test_unload_handles_unreachable_worker(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([
        Model(name="m", file="m.gguf", size_gb=1.0, loaded=True, loaded_pid=0,
              worker_nodes=["100.0.0.2:50052"]),
    ]))

    def _boom(*a, **kw):
        raise ConnectionError("dead")

    monkeypatch.setattr("pods.models.manager.httpx.post", _boom)

    mgr = ModelManager(store=store)
    result = mgr.unload("m")
    assert result["workers_stopped"] == []
    assert any("100.0.0.2" in s for s in result["workers_failed"])

    after = store.load()
    assert after.models[0].loaded is False
