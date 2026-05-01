from unittest.mock import MagicMock, patch

from pods.errors import NetworkError
from pods.network.tailscale import TailscaleStatus
from pods.preflight import PreflightChecker


def test_all_checks_pass():
    checker = PreflightChecker()
    with patch("pods.preflight.get_status", return_value=TailscaleStatus(running=True, peers=[])), \
         patch("pods.preflight.get_ip", return_value="100.1.2.3"), \
         patch("pods.preflight.shutil.which", return_value="/usr/bin/nvidia-smi"), \
         patch("pods.preflight.shutil.disk_usage", return_value=MagicMock(free=50 * 1024 ** 3)), \
         patch("pods.preflight.socket.socket") as mock_sock:
        mock_sock.return_value.__enter__.return_value.connect_ex.return_value = 1  # ports free
        results = checker.run()
    assert all(r.status != "block" for r in results)
    assert len(results) == 7


def test_tailscale_not_running_blocks_at_check_1():
    checker = PreflightChecker()
    with patch("pods.preflight.get_status", return_value=TailscaleStatus(running=False, peers=[])):
        results = checker.run()
    assert results[0].status == "block"
    assert len(results) == 1  # halts after first block


def test_tailscale_no_ip_blocks_at_check_2():
    checker = PreflightChecker()
    with patch("pods.preflight.get_status", return_value=TailscaleStatus(running=True, peers=[])), \
         patch("pods.preflight.get_ip", side_effect=NetworkError("no ip")):
        results = checker.run()
    assert results[1].status == "block"
    assert len(results) == 2


def test_no_nvidia_driver_warns_but_continues():
    checker = PreflightChecker()
    with patch("pods.preflight.get_status", return_value=TailscaleStatus(running=True, peers=[])), \
         patch("pods.preflight.get_ip", return_value="100.1.2.3"), \
         patch("pods.preflight.shutil.which", return_value=None), \
         patch("pods.preflight.shutil.disk_usage", return_value=MagicMock(free=50 * 1024 ** 3)), \
         patch("pods.preflight.socket.socket") as mock_sock:
        mock_sock.return_value.__enter__.return_value.connect_ex.return_value = 1
        results = checker.run()
    driver_result = next(r for r in results if r.name == "NVIDIA driver")
    assert driver_result.status == "warn"
    assert len(results) == 7  # all 7 ran


def test_port_8080_occupied_blocks():
    checker = PreflightChecker()
    with patch("pods.preflight.get_status", return_value=TailscaleStatus(running=True, peers=[])), \
         patch("pods.preflight.get_ip", return_value="100.1.2.3"), \
         patch("pods.preflight.shutil.which", return_value=None), \
         patch("pods.preflight.shutil.disk_usage", return_value=MagicMock(free=50 * 1024 ** 3)), \
         patch("pods.preflight.socket.socket") as mock_sock:
        mock_sock.return_value.__enter__.return_value.connect_ex.return_value = 0  # port occupied
        results = checker.run()
    port_result = next((r for r in results if "8080" in r.name), None)
    assert port_result is not None
    assert port_result.status == "block"


def test_low_disk_warns():
    checker = PreflightChecker()
    with patch("pods.preflight.get_status", return_value=TailscaleStatus(running=True, peers=[])), \
         patch("pods.preflight.get_ip", return_value="100.1.2.3"), \
         patch("pods.preflight.shutil.which", return_value=None), \
         patch("pods.preflight.shutil.disk_usage", return_value=MagicMock(free=10 * 1024 ** 3)), \
         patch("pods.preflight.socket.socket") as mock_sock:
        mock_sock.return_value.__enter__.return_value.connect_ex.return_value = 1
        results = checker.run()
    disk_result = next(r for r in results if r.name == "Disk space")
    assert disk_result.status == "warn"
