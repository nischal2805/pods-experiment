from datetime import datetime, timezone, timedelta

from click.testing import CliRunner

from pods.cli.worker import cmd as worker_cmd, _dead_workers
from pods.gateway.routes_internal import heartbeat, HeartbeatPayload
from pods.state.schema import Member, Pod, PodState
from pods.state.store import StateStore


def _state(members):
    pod = Pod(name="t", coordinator_ip="100.0.0.1")
    return PodState(pod=pod, members=members)


def _worker(name, last_seen_ago_s, node_id=None):
    return Member(
        node_id=node_id or f"id-{name}",
        name=name,
        tailscale_ip=f"100.0.0.{ord(name[-1]) % 250}",
        role="worker",
        os="linux",
        last_seen=datetime.now(timezone.utc) - timedelta(seconds=last_seen_ago_s),
    )


def test_dead_workers_returns_only_old():
    state = _state([_worker("w1", 30), _worker("w2", 700), _worker("w3", 1200)])
    dead = _dead_workers(state, datetime.now(timezone.utc))
    names = {m.name for m in dead}
    assert names == {"w2", "w3"}


def test_prune_command_removes_dead_workers(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_worker("w1", 30), _worker("w2", 700)]))
    monkeypatch.setattr("pods.cli.worker.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["prune", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Removed 1" in result.output

    after = store.load()
    assert {m.name for m in after.members} == {"w1"}


def test_prune_no_dead_workers(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_worker("w1", 30)]))
    monkeypatch.setattr("pods.cli.worker.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(worker_cmd, ["prune", "--yes"])
    assert "No dead workers" in result.output


def test_heartbeat_auto_removes_dead_members(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    sender = _worker("sender", 5, node_id="sender-id")
    dead = _worker("dead", 800, node_id="dead-id")
    coord = Member(
        node_id="coord-id", name="coord", tailscale_ip="100.0.0.1",
        role="coordinator", os="linux",
        last_seen=datetime.now(timezone.utc) - timedelta(seconds=999),  # coord excluded from sweep
    )
    store.save(_state([sender, dead, coord]))

    response = heartbeat(HeartbeatPayload(node_id="sender-id"), store=store)
    assert response == {"status": "ok"}

    after = store.load()
    names = {m.name for m in after.members}
    assert names == {"sender", "coord"}  # dead removed; coordinator kept


def test_heartbeat_sweep_does_not_remove_sender(tmp_path):
    # Edge: sender's own last_seen is old (clock skew) — must not remove self
    store = StateStore(path=tmp_path / "state.json")
    old_sender = _worker("old", 800, node_id="old-id")
    store.save(_state([old_sender]))

    heartbeat(HeartbeatPayload(node_id="old-id"), store=store)

    after = store.load()
    assert len(after.members) == 1
