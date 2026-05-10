"""Tests for fixes from CODE_REVIEW.md."""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from pods.errors import InferenceError
from pods.models.manager import _validate_rpc_hosts, ModelManager
from pods.platform import detect as detect_mod
from pods.state.schema import Model, Pod, PodState
from pods.state.store import StateStore


# ---- #13 RPC host validation ----

def test_rpc_host_validation_accepts_valid():
    hosts = ["100.0.0.2:50052", "100.64.1.5:50052"]
    assert _validate_rpc_hosts(hosts) == hosts


def test_rpc_host_validation_rejects_shell_injection():
    with pytest.raises(InferenceError, match="Invalid RPC host"):
        _validate_rpc_hosts(["100.0.0.2:50052; rm -rf /"])


def test_rpc_host_validation_rejects_missing_port():
    with pytest.raises(InferenceError):
        _validate_rpc_hosts(["100.0.0.2"])


def test_rpc_host_validation_rejects_hostname():
    with pytest.raises(InferenceError):
        _validate_rpc_hosts(["evil.com:50052"])


# ---- #6 symlink rejection in register ----

def test_register_rejects_symlink(tmp_path, monkeypatch):
    import os
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks not supported")
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    link = models_dir / "evil.gguf"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted")

    state_path = tmp_path / "state.json"
    store = StateStore(path=state_path)
    store.save(PodState(pod=Pod(name="t", coordinator_ip="100.0.0.1")))

    monkeypatch.setattr("pods.models.manager.MODELS_DIR", models_dir)
    mgr = ModelManager(store=store)
    with pytest.raises(InferenceError, match="symlink"):
        mgr.register("evil", "evil.gguf")


# ---- #5 platform detect timeout ----

def test_safe_run_handles_timeout():
    import subprocess
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 5)):
        result = detect_mod._safe_run(["nvidia-smi"])
    assert result is None


def test_safe_run_handles_missing_binary():
    import subprocess
    with patch.object(subprocess, "run", side_effect=FileNotFoundError()):
        result = detect_mod._safe_run(["nvidia-smi"])
    assert result is None


# ---- #10 state backup recovery ----

def test_load_recovers_from_backup_when_primary_corrupt(tmp_path):
    state_path = tmp_path / "state.json"
    backup_path = tmp_path / "state.json.bak"
    good = PodState(pod=Pod(name="t", coordinator_ip="100.0.0.1"))
    backup_path.write_text(good.model_dump_json(indent=2))
    state_path.write_text("{ THIS IS NOT JSON")

    store = StateStore(path=state_path)
    loaded = store.load()
    assert loaded.pod.name == "t"
    # Primary should be repaired from backup
    assert json.loads(state_path.read_text())["pod"]["name"] == "t"


def test_load_raises_when_both_corrupt(tmp_path):
    from pods.errors import StateError
    state_path = tmp_path / "state.json"
    backup_path = tmp_path / "state.json.bak"
    state_path.write_text("garbage")
    backup_path.write_text("also garbage")

    store = StateStore(path=state_path)
    with pytest.raises(StateError, match="both malformed"):
        store.load()


def test_save_writes_backup(tmp_path):
    state_path = tmp_path / "state.json"
    store = StateStore(path=state_path)
    s1 = PodState(pod=Pod(name="first", coordinator_ip="100.0.0.1"))
    store.save(s1)
    # No backup yet — first write
    assert not (tmp_path / "state.json.bak").exists()

    s2 = PodState(pod=Pod(name="second", coordinator_ip="100.0.0.1"))
    store.save(s2)
    # Now backup contains the FIRST state
    backup = tmp_path / "state.json.bak"
    assert backup.exists()
    assert json.loads(backup.read_text())["pod"]["name"] == "first"
