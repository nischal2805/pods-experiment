import json
from pathlib import Path

from click.testing import CliRunner

from pods.cli import leave as leave_cli
from pods.gateway.routes_internal import leave as leave_endpoint, LeavePayload
from pods.state.schema import Member, Model, Pod, PodState
from pods.state.store import StateStore


class _StubResp:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


def _setup_config(tmp_home, role: str = "worker"):
    pods_dir = tmp_home / ".pods"
    pods_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "coordinator_ip": "100.0.0.1",
        "node_id": "w1-id",
        "role": role,
        "internal_token": "t",
    }
    (pods_dir / "config.json").write_text(json.dumps(config))
    return pods_dir / "config.json"


def test_leave_no_config(tmp_path, monkeypatch):
    monkeypatch.setattr(leave_cli, "CONFIG_PATH", tmp_path / "missing.json")
    runner = CliRunner()
    result = runner.invoke(leave_cli.cmd, ["--yes"])
    assert result.exit_code == 1
    assert "not joined" in result.output


def test_leave_coordinator_blocked(tmp_path, monkeypatch):
    cfg = _setup_config(tmp_path, role="coordinator")
    monkeypatch.setattr(leave_cli, "CONFIG_PATH", cfg)
    runner = CliRunner()
    result = runner.invoke(leave_cli.cmd, ["--yes"])
    assert result.exit_code == 1
    assert "coordinator" in result.output


def test_leave_full_flow(tmp_path, monkeypatch):
    cfg = _setup_config(tmp_path)
    monkeypatch.setattr(leave_cli, "CONFIG_PATH", cfg)

    posts = []
    def _fake_post(url, **kw):
        posts.append(url)
        return _StubResp(200)

    monkeypatch.setattr(leave_cli.httpx, "post", _fake_post)

    runner = CliRunner()
    result = runner.invoke(leave_cli.cmd, ["--yes"])
    assert result.exit_code == 0, result.output
    assert "coordinator notified" in result.output
    assert "local agent shutdown signaled" in result.output
    assert "Left pod" in result.output
    assert not cfg.exists()  # default removes config

    assert any("/internal/leave" in p for p in posts)
    assert any("/internal/shutdown" in p for p in posts)


def test_leave_keeps_config_with_flag(tmp_path, monkeypatch):
    cfg = _setup_config(tmp_path)
    monkeypatch.setattr(leave_cli, "CONFIG_PATH", cfg)
    monkeypatch.setattr(leave_cli.httpx, "post", lambda *a, **kw: _StubResp(200))

    runner = CliRunner()
    result = runner.invoke(leave_cli.cmd, ["--yes", "--keep-config"])
    assert result.exit_code == 0, result.output
    assert cfg.exists()


def test_leave_unreachable_coordinator_continues(tmp_path, monkeypatch):
    cfg = _setup_config(tmp_path)
    monkeypatch.setattr(leave_cli, "CONFIG_PATH", cfg)

    def _boom(url, **kw):
        raise ConnectionError("dead")

    monkeypatch.setattr(leave_cli.httpx, "post", _boom)

    runner = CliRunner()
    result = runner.invoke(leave_cli.cmd, ["--yes"])
    assert result.exit_code == 0, result.output
    assert "coordinator unreachable" in result.output
    assert "Left pod" in result.output
    assert not cfg.exists()


# ---- coordinator endpoint tests ----

def _state(members, models=None):
    return PodState(
        pod=Pod(name="t", coordinator_ip="100.0.0.1"),
        members=members,
        models=models or [],
    )


def _coord():
    from datetime import datetime, timezone
    return Member(
        node_id="coord-id", name="coord", tailscale_ip="100.0.0.1",
        role="coordinator", os="linux", last_seen=datetime.now(timezone.utc),
    )


def _worker(name, ip, node_id):
    from datetime import datetime, timezone
    return Member(
        node_id=node_id, name=name, tailscale_ip=ip,
        role="worker", os="linux", last_seen=datetime.now(timezone.utc),
    )


def test_internal_leave_removes_worker(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_coord(), _worker("w1", "100.0.0.2", "w1-id")]))

    resp = leave_endpoint(LeavePayload(node_id="w1-id"), store=store)
    assert resp == {"status": "ok"}
    after = store.load()
    assert {m.node_id for m in after.members} == {"coord-id"}


def test_internal_leave_unknown_node(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_coord()]))
    resp = leave_endpoint(LeavePayload(node_id="ghost"), store=store)
    assert resp == {"status": "unknown_node"}


def test_internal_leave_refuses_coordinator(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state([_coord()]))
    resp = leave_endpoint(LeavePayload(node_id="coord-id"), store=store)
    assert resp == {"status": "unknown_node"}
    after = store.load()
    assert len(after.members) == 1


def test_internal_leave_clears_worker_from_models(tmp_path):
    store = StateStore(path=tmp_path / "state.json")
    model = Model(name="m", file="m.gguf", size_gb=1.0, loaded=True,
                  worker_nodes=["100.0.0.2:50052", "100.0.0.3:50052"])
    store.save(_state(
        [_coord(), _worker("w1", "100.0.0.2", "w1-id"), _worker("w2", "100.0.0.3", "w2-id")],
        models=[model],
    ))
    leave_endpoint(LeavePayload(node_id="w1-id"), store=store)
    after = store.load()
    assert after.models[0].worker_nodes == ["100.0.0.3:50052"]
