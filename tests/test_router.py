import pytest
from unittest.mock import patch
from pods.gateway.router import select_backend
from pods.state.schema import PodState, Pod, Model


def _state(models=None):
    pod = Pod(name="test", coordinator_ip="100.1.2.3")
    return PodState(pod=pod, models=models or [])


def _loaded_model(name="qwen32b"):
    return Model(name=name, file=f"{name}.gguf", size_gb=20.0, loaded=True)


def test_llamacpp_selected_when_model_loaded_and_reachable():
    state = _state([_loaded_model("qwen32b")])
    with patch("pods.gateway.router._is_reachable", return_value=True):
        name, url = select_backend("qwen32b", state)
    assert name == "llamacpp"
    assert url == "http://localhost:8081"


def test_exo_selected_when_llamacpp_unreachable():
    state = _state([_loaded_model("qwen32b")])
    def mock_reachable(url):
        return "52415" in url
    with patch("pods.gateway.router._is_reachable", side_effect=mock_reachable):
        name, url = select_backend("qwen32b", state)
    assert name == "exo"


def test_ollama_selected_when_no_model_loaded():
    state = _state()
    def mock_reachable(url):
        return "11434" in url
    with patch("pods.gateway.router._is_reachable", side_effect=mock_reachable):
        name, url = select_backend("llama3", state)
    assert name == "ollama"


def test_raises_when_all_backends_fail():
    state = _state([_loaded_model("qwen32b")])
    with patch("pods.gateway.router._is_reachable", return_value=False):
        with pytest.raises(Exception):
            select_backend("qwen32b", state)


def test_raises_when_no_model_and_ollama_unreachable():
    state = _state()
    with patch("pods.gateway.router._is_reachable", return_value=False):
        with pytest.raises(Exception):
            select_backend("qwen32b", state)


def test_ollama_is_last_resort():
    state = _state([_loaded_model("qwen32b")])
    calls = []
    def mock_reachable(url):
        calls.append(url)
        return False
    with patch("pods.gateway.router._is_reachable", side_effect=mock_reachable):
        with pytest.raises(Exception):
            select_backend("qwen32b", state)
    assert "11434" in calls[-1]
