"""Tests for Windows WSL2 proxy port forwarding."""
from unittest.mock import MagicMock, patch

import pytest

from pods.errors import SetupError
from pods.platform.windows import WindowsProxy


def _make_result(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


class TestGetWslIp:
    def test_returns_first_ip(self):
        proxy = WindowsProxy()
        with patch("subprocess.run", return_value=_make_result(0, "172.20.0.1 172.20.0.2\n")):
            assert proxy._get_wsl_ip() == "172.20.0.1"

    def test_raises_when_command_fails(self):
        proxy = WindowsProxy()
        with patch("subprocess.run", return_value=_make_result(1, "")):
            with pytest.raises(SetupError):
                proxy._get_wsl_ip()

    def test_raises_when_stdout_empty(self):
        proxy = WindowsProxy()
        with patch("subprocess.run", return_value=_make_result(0, "   ")):
            with pytest.raises(SetupError):
                proxy._get_wsl_ip()


class TestSetupPortForwarding:
    def test_adds_portproxy_rule(self):
        proxy = WindowsProxy()
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(cmd)
            return _make_result(0)

        with patch.object(proxy, "_get_wsl_ip", return_value="172.20.0.1"):
            with patch("subprocess.run", side_effect=fake_run):
                proxy.setup_port_forwarding(8080)

        delete_call = calls[0]
        add_call = calls[1]
        assert "delete" in delete_call
        assert "listenport=8080" in delete_call
        assert "add" in add_call
        assert "listenport=8080" in add_call
        assert "connectaddress=172.20.0.1" in add_call

    def test_raises_on_netsh_failure(self):
        proxy = WindowsProxy()

        def fake_run(cmd, **_kw):
            if "add" in cmd:
                return _make_result(1, stderr="Access denied")
            return _make_result(0)

        with patch.object(proxy, "_get_wsl_ip", return_value="172.20.0.1"):
            with patch("subprocess.run", side_effect=fake_run):
                with pytest.raises(SetupError, match="Failed to forward port"):
                    proxy.setup_port_forwarding(8080)

    def test_idempotent_delete_ignored_on_failure(self):
        proxy = WindowsProxy()
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(cmd)
            # delete fails (no existing rule) — should be ignored
            if "delete" in cmd:
                return _make_result(1)
            return _make_result(0)

        with patch.object(proxy, "_get_wsl_ip", return_value="172.20.0.1"):
            with patch("subprocess.run", side_effect=fake_run):
                proxy.setup_port_forwarding(8080)  # should not raise

        assert any("add" in c for c in calls)
