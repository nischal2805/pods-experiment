from unittest.mock import MagicMock, patch

import pytest

from pods.errors import InferenceError
from pods.inference.base import EngineStatus, HealthStatus
from pods.inference.exo import ExoEngine
from pods.inference.fallback import FallbackOrchestrator
from pods.inference.llamacpp import LlamaCppEngine
from pods.inference.ollama import OllamaEngine


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


def test_tail_log_returns_last_n_lines(tmp_path):
    from pods.inference.llamacpp import _tail_log
    p = tmp_path / "x.log"
    p.write_text("\n".join(f"line{i}" for i in range(50)) + "\n")
    out = _tail_log(p, n=5)
    assert "line45" in out
    assert "line49" in out
    assert "line0" not in out


def test_tail_log_missing_file(tmp_path):
    from pods.inference.llamacpp import _tail_log
    out = _tail_log(tmp_path / "nope.log", n=5)
    assert "log unavailable" in out


def test_health_timeout_includes_log_tail(tmp_path, monkeypatch):
    from pods.inference import llamacpp as mod
    log_path = tmp_path / "llama-server.log"
    log_path.write_text("startup line\nERROR: cuda init failed\nbailing out\n")
    monkeypatch.setattr(mod, "LLAMA_SERVER_LOG", log_path)
    monkeypatch.setattr(mod, "HEALTH_TIMEOUT", 0)  # immediate timeout

    engine = mod.LlamaCppEngine()
    with patch("httpx.get", side_effect=Exception("refused")):
        with pytest.raises(InferenceError) as ei:
            engine._wait_for_health()
    assert "ERROR: cuda init failed" in ei.value.reason
    assert "bailing out" in ei.value.reason


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
        name, _ = FallbackOrchestrator().start_best_engine({})

    assert name == "llama.cpp RPC"
    mock_engine.start.assert_called_once_with({})


def test_fallback_skips_to_exo_when_llamacpp_fails():
    llamacpp_mock = MagicMock()
    llamacpp_mock.detect.return_value = True
    llamacpp_mock.health.return_value = HealthStatus(EngineStatus.STOPPED, "process died")

    exo_mock = MagicMock()
    exo_mock.detect.return_value = True
    exo_mock.health.return_value = HealthStatus(EngineStatus.RUNNING)

    with patch("pods.inference.fallback.sys.platform", "darwin"), \
         patch("pods.inference.fallback.LlamaCppEngine", return_value=llamacpp_mock), \
         patch("pods.inference.fallback.ExoEngine", return_value=exo_mock):
        name, _ = FallbackOrchestrator().start_best_engine({})

    assert name == "exo"


def test_fallback_skips_unavailable_engines():
    ollama_mock = MagicMock()
    ollama_mock.detect.return_value = True
    ollama_mock.health.return_value = HealthStatus(EngineStatus.RUNNING)

    with patch("pods.inference.fallback.LlamaCppEngine.detect", return_value=False), \
         patch("pods.inference.fallback.ExoEngine.detect", return_value=False), \
         patch("pods.inference.fallback.OllamaEngine", return_value=ollama_mock):
        name, _ = FallbackOrchestrator().start_best_engine({})

    assert name == "Ollama"


def test_fallback_excludes_exo_on_non_darwin():
    with patch("pods.inference.fallback.sys.platform", "linux"):
        from pods.inference.fallback import _engine_list
        names = [n for n, _ in _engine_list()]
    assert "exo" not in names
    assert "llama.cpp RPC" in names
    assert "Ollama" in names


def test_fallback_includes_exo_on_darwin():
    with patch("pods.inference.fallback.sys.platform", "darwin"):
        from pods.inference.fallback import _engine_list
        names = [n for n, _ in _engine_list()]
    assert "exo" in names
