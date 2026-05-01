from unittest.mock import MagicMock, patch

from pods.inference.base import EngineStatus
from pods.inference.detector import viable_engines
from pods.inference.llamacpp import LlamaCppEngine
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
