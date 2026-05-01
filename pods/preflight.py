import shutil
import socket
from dataclasses import dataclass
from pathlib import Path

from .errors import NetworkError
from .network.tailscale import get_ip, get_status


@dataclass
class CheckResult:
    name: str
    status: str  # "pass" | "warn" | "block"
    message: str


class PreflightChecker:
    REQUIRED_DISK_GB = 25

    def run(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        checks = [
            self._check_tailscale_running,
            self._check_tailscale_ip,
            self._check_nvidia_driver,
            self._check_cuda,
            self._check_disk_space,
            self._check_port_8080,
            self._check_port_8081,
        ]
        for check in checks:
            result = check()
            icon = "✓" if result.status == "pass" else ("⚠" if result.status == "warn" else "✗")
            print(f"  {icon} {result.name}: {result.message}")
            results.append(result)
            if result.status == "block":
                break
        return results

    def _check_tailscale_running(self) -> CheckResult:
        status = get_status()
        if not status.running:
            return CheckResult(
                "Tailscale running", "block",
                "Not running — install from https://tailscale.com/download",
            )
        return CheckResult("Tailscale running", "pass", "OK")

    def _check_tailscale_ip(self) -> CheckResult:
        try:
            ip = get_ip()
            return CheckResult("Tailscale IP assigned", "pass", ip)
        except NetworkError:
            return CheckResult(
                "Tailscale IP assigned", "block",
                "Not assigned — run 'tailscale up'",
            )

    def _check_nvidia_driver(self) -> CheckResult:
        if shutil.which("nvidia-smi"):
            return CheckResult("NVIDIA driver", "pass", "nvidia-smi found")
        return CheckResult(
            "NVIDIA driver", "warn",
            "Not found — node will use CPU inference",
        )

    def _check_cuda(self) -> CheckResult:
        if shutil.which("nvcc"):
            return CheckResult("CUDA toolkit", "pass", "nvcc found")
        return CheckResult(
            "CUDA toolkit", "warn",
            "Not found — falls back to exo or Ollama",
        )

    def _check_disk_space(self) -> CheckResult:
        pods_dir = Path.home() / "pods"
        pods_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(pods_dir)
        free_gb = usage.free // (1024 ** 3)
        if free_gb < self.REQUIRED_DISK_GB:
            return CheckResult(
                "Disk space", "warn",
                f"{free_gb}GB free — models need 5–20GB each",
            )
        return CheckResult("Disk space", "pass", f"{free_gb}GB free")

    def _check_port_8080(self) -> CheckResult:
        return self._port_check(8080, "Port 8080")

    def _check_port_8081(self) -> CheckResult:
        return self._port_check(8081, "Port 8081")

    def _port_check(self, port: int, name: str) -> CheckResult:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return CheckResult(
                    name, "block",
                    f"Port {port} already in use — free it before running pods",
                )
        return CheckResult(name, "pass", "Available")
