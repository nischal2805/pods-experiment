import stat
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from pods.platform.setup import validate_existing_binaries, download_and_install_binaries
from pods.platform.detect import PlatformInfo
from pods.errors import PlatformError


def test_validate_missing_llama_server(tmp_path):
    rpc = tmp_path / "rpc-server"
    rpc.touch()
    # Mock stat to indicate executable
    original_stat = Path.stat
    def mock_stat(self):
        real_stat = original_stat(self)
        if str(self) == str(rpc):
            # Return a stat object with executable bit set
            return MagicMock(st_mode=real_stat.st_mode | stat.S_IEXEC)
        return real_stat

    with patch("pods.platform.setup.LLAMA_SERVER", tmp_path / "llama-server"), \
         patch("pods.platform.setup.RPC_SERVER", rpc), \
         patch.object(Path, "stat", mock_stat):
        with pytest.raises(PlatformError, match="not found"):
            validate_existing_binaries()


def test_validate_missing_rpc_server(tmp_path):
    ls = tmp_path / "llama-server"
    ls.touch()
    # Mock stat to indicate executable
    original_stat = Path.stat
    def mock_stat(self):
        real_stat = original_stat(self)
        if str(self) == str(ls):
            # Return a stat object with executable bit set
            return MagicMock(st_mode=real_stat.st_mode | stat.S_IEXEC)
        return real_stat

    with patch("pods.platform.setup.LLAMA_SERVER", ls), \
         patch("pods.platform.setup.RPC_SERVER", tmp_path / "rpc-server"), \
         patch.object(Path, "stat", mock_stat):
        with pytest.raises(PlatformError, match="not found"):
            validate_existing_binaries()


def test_validate_non_executable(tmp_path):
    ls = tmp_path / "llama-server"
    rpc = tmp_path / "rpc-server"
    ls.touch()
    rpc.touch()
    ls.chmod(0o644)  # not executable

    with patch("pods.platform.setup.LLAMA_SERVER", ls), \
         patch("pods.platform.setup.RPC_SERVER", rpc):
        with pytest.raises(PlatformError, match="not executable"):
            validate_existing_binaries()


def test_validate_both_present_and_executable(tmp_path):
    ls = tmp_path / "llama-server"
    rpc = tmp_path / "rpc-server"
    for b in [ls, rpc]:
        b.touch()

    # Mock stat to indicate both are executable
    original_stat = Path.stat
    def mock_stat(self):
        real_stat = original_stat(self)
        if str(self) in (str(ls), str(rpc)):
            # Return a stat object with executable bit set
            return MagicMock(st_mode=real_stat.st_mode | stat.S_IEXEC)
        return real_stat

    with patch("pods.platform.setup.LLAMA_SERVER", ls), \
         patch("pods.platform.setup.RPC_SERVER", rpc), \
         patch.object(Path, "stat", mock_stat):
        validate_existing_binaries()  # must not raise


def test_download_raises_not_implemented():
    info = PlatformInfo(os="linux", gpu_vendor="nvidia", cuda_version="12.2", vram_gb=8)
    with pytest.raises(NotImplementedError):
        download_and_install_binaries(info)
