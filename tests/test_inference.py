import pytest
from pods.inference.detector import viable_engines
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
