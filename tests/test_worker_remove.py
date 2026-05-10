from datetime import datetime, timezone

from click.testing import CliRunner

from pods.cli.worker import cmd as worker_cmd
from pods.state.schema import Member, Model, Pod, PodState
from pods.state.store import StateStore


def _state(members, models=None):
    return PodState(
        pod=Pod(name="t", coordinator_ip="100.0.0.1"),
        members=members,
        models=models or [],
    )


def _coord():
    return Member(
        node_id="coord-id", name="coord", tailscale_ip="100.0.0.1",
        role="coordinator", os="linux",
        last_seen=datetime.now(timezone.utc),
    )


def _worker(name, ip, node_id):
    return Member(
        node_id=node_id, name=name, tailscale_ip=ip,
        role="worker", os="linux",
        last_seen=datetime.now(timezone.utc),
    )


def test_remove_by_ip(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([
        _coord(),
        _worker("w1", "100.0.0.2", "w1-id"),
        _worker("w2", "100.0.0.3", "w2-id"),
    ]))
    monkeypatch.setattr("pods.cli.worker.StateStore", lambda: store)
    monkeypatch.setattr("pods.cli.worker.httpx.post", lambda *a, **kw: _RaiseConn())

    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["remove", "100.0.0.2", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Removed worker w1" in result.output

    after = store.load()
    assert {m.tailscale_ip for m in after.members} == {"100.0.0.1", "100.0.0.3"}


def test_remove_by_node_id(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_coord(), _worker("w1", "100.0.0.2", "w1-id")]))
    monkeypatch.setattr("pods.cli.worker.StateStore", lambda: store)
    monkeypatch.setattr("pods.cli.worker.httpx.post", lambda *a, **kw: _RaiseConn())

    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["remove", "w1-id", "--yes"])
    assert result.exit_code == 0, result.output

    after = store.load()
    assert {m.node_id for m in after.members} == {"coord-id"}


def test_remove_unknown(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_coord(), _worker("w1", "100.0.0.2", "w1-id")]))
    monkeypatch.setattr("pods.cli.worker.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["remove", "100.99.99.99", "--yes"])
    assert result.exit_code == 1
    assert "No worker matches" in result.output


def test_remove_unreachable_agent_still_removes(tmp_path, monkeypatch):
    """Agent dead → remove from state anyway."""
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_coord(), _worker("w1", "100.0.0.2", "w1-id")]))
    monkeypatch.setattr("pods.cli.worker.StateStore", lambda: store)

    def _boom(*a, **kw):
        raise ConnectionError("agent dead")

    monkeypatch.setattr("pods.cli.worker.httpx.post", _boom)

    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["remove", "100.0.0.2", "--yes"])
    assert result.exit_code == 0, result.output
    assert "agent unreachable" in result.output

    after = store.load()
    assert len(after.members) == 1


def test_remove_clears_worker_from_loaded_model(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    model = Model(name="m", file="m.gguf", size_gb=1.0, loaded=True,
                  worker_nodes=["100.0.0.2:50052", "100.0.0.3:50052"])
    store.save(_state(
        [_coord(), _worker("w1", "100.0.0.2", "w1-id"), _worker("w2", "100.0.0.3", "w2-id")],
        models=[model],
    ))
    monkeypatch.setattr("pods.cli.worker.StateStore", lambda: store)
    monkeypatch.setattr("pods.cli.worker.httpx.post", lambda *a, **kw: _RaiseConn())

    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["remove", "100.0.0.2", "--yes"])
    assert result.exit_code == 0, result.output

    after = store.load()
    assert after.models[0].worker_nodes == ["100.0.0.3:50052"]


class _RaiseConn:
    """Stand-in for httpx Response — never used because httpx.post replaced."""
    status_code = 200
