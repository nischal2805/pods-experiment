"""Regression tests for the 2026-06-10 codebase review fixes."""
from unittest.mock import MagicMock, patch

import pytest

from pods.errors import InferenceError
from pods.state.schema import Model, Pod, PodState
from pods.state.store import StateStore


def test_gateway_does_not_expose_state_path_query_param():
    """Depends(StateStore) used to expose the store's `path` ctor arg as a
    client-controllable query parameter on every authed endpoint."""
    from pods.gateway.app import app

    spec = app.openapi()
    for path, methods in spec["paths"].items():
        for method in methods.values():
            params = [p["name"] for p in method.get("parameters", [])]
            assert "path" not in params, f"`path` query param leaked on {path}"


async def test_stream_to_backend_raises_before_response_on_connect_failure():
    """Connection errors must surface as InferenceError (-> 503) before the
    StreamingResponse is returned, not crash mid-stream after a 200."""
    from pods.gateway.proxy import stream_to_backend

    with pytest.raises(InferenceError, match="Cannot connect"):
        # Port 9 (discard) — nothing listens there.
        await stream_to_backend("http://127.0.0.1:9", {"model": "x"})


def test_agent_start_rpc_stops_previous_engine(monkeypatch):
    """A second start-rpc must stop the old rpc-server instead of orphaning it."""
    from pods.agent import server

    first = MagicMock()
    second = MagicMock()
    engines = iter([first, second])
    monkeypatch.setattr(server, "LlamaCppEngine", lambda: next(engines))
    monkeypatch.setattr(server, "_engine", None)

    server.start_rpc(_=None)
    assert server._engine is first
    first.stop.assert_not_called()

    server.start_rpc(_=None)
    assert server._engine is second
    first.stop.assert_called_once()


def test_restart_llamacpp_failure_marks_model_unloaded(tmp_path, monkeypatch):
    """If the coordinator restart fails mid-attach, the model must not stay
    marked loaded with a dead pid."""
    from pods.gateway import routes_internal

    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="t", coordinator_ip="100.0.0.1")
    model = Model(name="m", file="m.gguf", size_gb=1.0, loaded=True, loaded_pid=12345,
                  worker_nodes=["100.0.0.2:50052"])
    store.save(PodState(pod=pod, models=[model]))

    failing_engine = MagicMock()
    failing_engine.start.side_effect = RuntimeError("boom")
    monkeypatch.setattr(routes_internal, "LlamaCppEngine", lambda: failing_engine)
    monkeypatch.setattr(routes_internal, "_start_rpc_on_workers", lambda s: [])

    routes_internal._restart_llamacpp("m", old_pid=0, store=store)

    fresh = store.load().models[0]
    assert fresh.loaded is False
    assert fresh.loaded_pid == 0
    assert fresh.worker_nodes == []
    assert fresh.reloading is False


def test_register_rejects_sibling_directory_prefix(tmp_path):
    """`~/pods/models-evil` must not pass the containment check just because
    its string form starts with the models dir path."""
    from pods.models.manager import ModelManager

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    evil_dir = tmp_path / "models-evil"
    evil_dir.mkdir()
    (evil_dir / "x.gguf").write_text("fake")

    store = StateStore(path=tmp_path / "state.json")
    store.save(PodState(pod=Pod(name="t", coordinator_ip="100.0.0.1")))
    mgr = ModelManager(store=store)

    with patch("pods.models.manager.MODELS_DIR", models_dir):
        with pytest.raises(InferenceError):
            mgr.register("evil", "../models-evil/x.gguf")


def test_check_wsl_returns_false_when_wsl_missing():
    from pods.platform.windows import WindowsProxy

    with patch("subprocess.run", side_effect=FileNotFoundError("wsl")):
        assert WindowsProxy().check_wsl() is False


def test_tailscale_ping_survives_timeout():
    import subprocess as sp

    from pods.network import tailscale

    with patch("pods.network.tailscale.subprocess.run",
               side_effect=sp.TimeoutExpired(cmd="tailscale", timeout=15)):
        result = tailscale.ping("100.0.0.2")
    assert result["direct"] is False


def test_amd_vram_parsed_from_rocm_smi():
    from pods.platform import detect

    rocm_out = "GPU[0] : VRAM Total Memory (B): 17163091968\n"

    def fake_run(args, timeout=5):
        r = MagicMock()
        if args[0] == "nvidia-smi":
            return None
        r.returncode = 0
        r.stdout = rocm_out
        return r

    with patch.object(detect, "_safe_run", side_effect=fake_run):
        vendor, cuda, vram = detect._detect_gpu_linux()
    assert vendor == "amd"
    assert vram == 15  # 17163091968 bytes ≈ 15 GiB
