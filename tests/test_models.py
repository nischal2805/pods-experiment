from unittest.mock import patch

import pytest

from pods.errors import InferenceError
from pods.models.registry import list_names, resolve
from pods.state.schema import Pod, PodState
from pods.state.store import StateStore


def test_resolve_known_name():
    entry = resolve("qwen32b")
    assert entry["repo"] == "Qwen/Qwen2.5-32B-Instruct-GGUF"
    assert entry["filename"] == "qwen2.5-32b-instruct-q4_k_m.gguf"


def test_resolve_unknown_name():
    with pytest.raises(KeyError):
        resolve("nonexistent-model")


def test_list_names():
    names = list_names()
    assert "qwen32b" in names
    assert "qwen7b" in names
    assert "gemma9b" in names
    assert "llama8b" in names
    assert len(names) == 6


def test_add_unknown_model_raises(tmp_path):
    from pods.models.manager import ModelManager

    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    store.save(PodState(pod=pod))
    mgr = ModelManager(store=store)
    with pytest.raises(InferenceError):
        mgr.add("no-such-model")


def test_register_missing_file_raises(tmp_path):
    from pods.models.manager import ModelManager

    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    store.save(PodState(pod=pod))
    mgr = ModelManager(store=store)
    with patch("pods.models.manager.MODELS_DIR", tmp_path / "models"):
        with pytest.raises(InferenceError, match="not found"):
            mgr.register("mymodel", "nonexistent.gguf")


def test_register_saves_to_state(tmp_path):
    from pods.models.manager import ModelManager

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "mymodel.gguf").touch()
    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    store.save(PodState(pod=pod))
    mgr = ModelManager(store=store)
    with patch("pods.models.manager.MODELS_DIR", models_dir):
        model = mgr.register("mymodel", "mymodel.gguf")
    assert model.name == "mymodel"
    loaded_state = store.load()
    assert any(m.name == "mymodel" for m in loaded_state.models)


def test_list_models(tmp_path):
    from pods.models.manager import ModelManager
    from pods.state.schema import Model

    store = StateStore(path=tmp_path / "state.json")
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    m = Model(name="qwen7b", file="qwen7b.gguf", size_gb=5.0)
    store.save(PodState(pod=pod, models=[m]))
    mgr = ModelManager(store=store)
    models = mgr.list_models()
    assert len(models) == 1
    assert models[0].name == "qwen7b"
