import shutil
import socket
import subprocess
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
            self._check_port_50052,
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
        if not shutil.which("nvidia-smi"):
            return CheckResult(
                "CUDA runtime", "warn",
                "nvidia-smi not found — falls back to exo or Ollama",
            )
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0:
                # nvidia-smi header line contains "CUDA Version: X.Y"
                ver_out = subprocess.run(
                    ["nvidia-smi"],
                    capture_output=True, text=True, timeout=5,
                )
                for line in ver_out.stdout.splitlines():
                    if "CUDA Version" in line:
                        cuda_ver = line.split("CUDA Version:")[-1].strip().split()[0]
                        return CheckResult("CUDA runtime", "pass", f"CUDA {cuda_ver}")
                return CheckResult("CUDA runtime", "pass", "nvidia-smi OK")
        except Exception:
            pass
        return CheckResult(
            "CUDA runtime", "warn",
            "nvidia-smi found but CUDA version unreadable — GPU may still work",
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
        return self._port_check(8080, "Port 8080", block=True)

    def _check_port_8081(self) -> CheckResult:
        return self._port_check(8081, "Port 8081", block=True)

    def _check_port_50052(self) -> CheckResult:
        return self._port_check(50052, "Port 50052 (rpc-server)", block=False)

    # Patterns matched against /proc cmdlines (Linux) or ps output (Mac/WSL)
    _PODS_PATTERNS = [
        "uvicorn pods.gateway",
        "uvicorn pods.agent",
        "llama-server",
        "rpc-server",
    ]

    def _port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _try_free_port(self, port: int) -> bool:
        """Kill known pods processes occupying *port*. Return True if port is now free."""
        for pattern in self._PODS_PATTERNS:
            try:
                subprocess.run(
                    ["pkill", "-f", pattern],
                    capture_output=True, timeout=3,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        import time
        time.sleep(0.5)
        return not self._port_in_use(port)

    def _port_check(self, port: int, name: str, block: bool = True) -> CheckResult:
        if not self._port_in_use(port):
            return CheckResult(name, "pass", "Available")

        freed = self._try_free_port(port)
        if freed:
            return CheckResult(name, "pass", f"Freed stale pods process on {port}")

        severity = "block" if block else "warn"
        return CheckResult(
            name, severity,
            f"Port {port} in use by non-pods process — free it before running pods",
        )
