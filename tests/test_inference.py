import shutil
from unittest.mock import MagicMock, patch

import pytest

from pods.errors import InferenceError
from pods.inference.base import EngineStatus, HealthStatus
from pods.inference.detector import viable_engines
from pods.inference.exo import ExoEngine
from pods.inference.fallback import FallbackOrchestrator
from pods.inference.llamacpp import LlamaCppEngine
from pods.inference.ollama import OllamaEngine
from pods.platform.detect import PlatformInfo


def test_nvidia_linux_gets_llamacpp_first():
    info = PlatformInfo(os="linux", gpu_vendor="nvidia", cuda_version="12.2", vram_gb=8)
    engines = viable_engines(info)
    assert engines[0] == "llamacpp"
    assert "ollama" in engines


def test_nvidia_wsl2_gets_llamacpp_first():
    info = PlatformInfo(os="wsl2", gpu_vendor="nvidia", cuda_version="12.2", vram_gb=8)
    engines = viable_engines(info)
    assert engines[0] == "llamacpp"


def test_apple_silicon_prefers_exo():
    info = PlatformInfo(os="mac", gpu_vendor="apple", arch="arm64")
    engines = viable_engines(info)
    assert engines[0] == "exo"
    assert "ollama" in engines


def test_windows_gets_ollama_only():
    info = PlatformInfo(os="windows", gpu_vendor="none")
    engines = viable_engines(info)
    assert engines == ["ollama"]


def test_cpu_only_linux_gets_exo_then_ollama():
    info = PlatformInfo(os="linux", gpu_vendor="none")
    engines = viable_engines(info)
    assert "exo" in engines
    assert "ollama" in engines
    assert engines.index("exo") < engines.index("ollama")


def test_ollama_always_last():
    for vendor in ["nvidia", "amd", "apple", "none"]:
        info = PlatformInfo(os="linux", gpu_vendor=vendor)
        engines = viable_engines(info)
        assert engines[-1] == "ollama"


def test_llamacpp_detect_false_when_binaries_missing(tmp_path):
    with patch("pods.inference.llamacpp.LLAMA_SERVER", tmp_path / "llama-server"), \
         patch("pods.inference.llamacpp.RPC_SERVER", tmp_path / "rpc-server"):
        engine = LlamaCppEngine()
        assert engine.detect() is False


def test_llamacpp_detect_true_when_binaries_present(tmp_path):
    ls = tmp_path / "llama-server"
    rpc = tmp_path / "rpc-server"
    ls.touch()
    rpc.touch()
    with patch("pods.inference.llamacpp.LLAMA_SERVER", ls), \
         patch("pods.inference.llamacpp.RPC_SERVER", rpc):
        engine = LlamaCppEngine()
        assert engine.detect() is True


def test_llamacpp_stop_with_no_process():
    engine = LlamaCppEngine()
    engine.stop()  # must not raise


def test_llamacpp_health_stopped_when_no_process():
    engine = LlamaCppEngine()
    engine._mode = "coordinator"
    with patch("httpx.get", side_effect=Exception("connection refused")):
        result = engine.health()
    assert result.status == EngineStatus.STOPPED


def test_llamacpp_worker_health_running_while_process_alive():
    engine = LlamaCppEngine()
    engine._mode = "worker"
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # still running
    engine._process = mock_proc
    result = engine.health()
    assert result.status == EngineStatus.RUNNING


def test_llamacpp_worker_health_stopped_when_process_dead():
    engine = LlamaCppEngine()
    engine._mode = "worker"
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1  # exited
    engine._process = mock_proc
    result = engine.health()
    assert result.status == EngineStatus.STOPPED


def test_llamacpp_get_models_empty_when_not_running():
    engine = LlamaCppEngine()
    with patch("httpx.get", side_effect=Exception("refused")):
        models = engine.get_models()
    assert models == []


def test_exo_detect_false_when_not_installed():
    with patch("pods.inference.exo.shutil.which", return_value=None):
        assert ExoEngine().detect() is False


def test_exo_detect_true_when_installed():
    with patch("pods.inference.exo.shutil.which", return_value="/usr/bin/exo"):
        assert ExoEngine().detect() is True


def test_exo_health_stopped_when_not_running():
    with patch("httpx.get", side_effect=Exception("refused")):
        assert ExoEngine().health().status == EngineStatus.STOPPED


def test_exo_get_models_empty_when_not_running():
    with patch("httpx.get", side_effect=Exception("refused")):
        assert ExoEngine().get_models() == []


def test_ollama_detect_false_when_not_installed():
    with patch("pods.inference.ollama.shutil.which", return_value=None):
        assert OllamaEngine().detect() is False


def test_ollama_detect_true_when_installed():
    with patch("pods.inference.ollama.shutil.which", return_value="/usr/bin/ollama"):
        assert OllamaEngine().detect() is True


def test_ollama_health_stopped_when_not_running():
    with patch("httpx.get", side_effect=Exception("refused")):
        assert OllamaEngine().health().status == EngineStatus.STOPPED


def test_ollama_get_models_empty_when_not_running():
    with patch("httpx.get", side_effect=Exception("refused")):
        assert OllamaEngine().get_models() == []


def test_ollama_stop_with_no_process():
    OllamaEngine().stop()  # must not raise


def test_fallback_raises_when_all_unavailable():
    with patch("pods.inference.fallback.LlamaCppEngine.detect", return_value=False), \
         patch("pods.inference.fallback.ExoEngine.detect", return_value=False), \
         patch("pods.inference.fallback.OllamaEngine.detect", return_value=False):
        with pytest.raises(InferenceError, match="No inference engine"):
            FallbackOrchestrator().start_best_engine({})


def test_fallback_returns_first_working_engine():
    mock_engine = MagicMock()
    mock_engine.detect.return_value = True
    mock_engine.health.return_value = HealthStatus(EngineStatus.RUNNING)

    with patch("pods.inference.fallback.LlamaCppEngine", return_value=mock_engine):
        name, engine = FallbackOrchestrator().start_best_engine({})

    assert name == "llama.cpp RPC"
    mock_engine.start.assert_called_once_with({})


def test_fallback_skips_to_exo_when_llamacpp_fails():
    llamacpp_mock = MagicMock()
    llamacpp_mock.detect.return_value = True
    llamacpp_mock.health.return_value = HealthStatus(EngineStatus.STOPPED, "process died")

    exo_mock = MagicMock()
    exo_mock.detect.return_value = True
    exo_mock.health.return_value = HealthStatus(EngineStatus.RUNNING)

    with patch("pods.inference.fallback.LlamaCppEngine", return_value=llamacpp_mock), \
         patch("pods.inference.fallback.ExoEngine", return_value=exo_mock):
        name, engine = FallbackOrchestrator().start_best_engine({})

    assert name == "exo"


def test_fallback_skips_unavailable_engines():
    ollama_mock = MagicMock()
    ollama_mock.detect.return_value = True
    ollama_mock.health.return_value = HealthStatus(EngineStatus.RUNNING)

    with patch("pods.inference.fallback.LlamaCppEngine.detect", return_value=False), \
         patch("pods.inference.fallback.ExoEngine.detect", return_value=False), \
         patch("pods.inference.fallback.OllamaEngine", return_value=ollama_mock):
        name, engine = FallbackOrchestrator().start_best_engine({})

    assert name == "Ollama"
