import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PlatformInfo:
    os: str           # "linux" | "wsl2" | "mac" | "windows"
    gpu_vendor: str   # "nvidia" | "amd" | "apple" | "none"
    cuda_version: str = ""
    vram_gb: int = 0
    arch: str = ""


def _is_wsl2() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except FileNotFoundError:
        return False


_GPU_PROBE_TIMEOUT_S = 5


def _safe_run(args: list[str], timeout: int = _GPU_PROBE_TIMEOUT_S):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _detect_gpu_linux() -> tuple[str, str, int]:
    # NVIDIA
    result = _safe_run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    if result is not None and result.returncode == 0 and result.stdout.strip():
        lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip().isdigit()]
        vram_mb = sum(int(ln) for ln in lines)
        vram_gb = vram_mb // 1024

        cuda_version = ""
        # Prefer nvcc (toolkit version); fall back to nvidia-smi header (driver max CUDA)
        nvcc = _safe_run(["nvcc", "--version"])
        if nvcc is not None and nvcc.returncode == 0:
            m = re.search(r"release (\d+\.\d+)", nvcc.stdout)
            if m:
                cuda_version = m.group(1)
        if not cuda_version:
            smi = _safe_run(["nvidia-smi"])
            if smi is not None and smi.returncode == 0:
                m = re.search(r"CUDA Version:\s*(\d+\.\d+)", smi.stdout)
                if m:
                    cuda_version = m.group(1)
        return "nvidia", cuda_version, vram_gb

    # AMD
    result = _safe_run(["rocm-smi", "--showmeminfo", "vram"])
    if result is not None and result.returncode == 0:
        return "amd", "", 0

    return "none", "", 0


def _detect_gpu_mac() -> tuple[str, str, int]:
    result = _safe_run(["system_profiler", "SPDisplaysDataType"], timeout=10)
    if result is not None and "Apple" in result.stdout:
        return "apple", "", 0
    return "none", "", 0


def detect_platform() -> PlatformInfo:
    system = platform.system().lower()
    arch = platform.machine().lower()

    if system == "windows":
        return PlatformInfo(os="windows", gpu_vendor="none", arch=arch)

    if system == "darwin":
        vendor, cuda, vram = _detect_gpu_mac()
        return PlatformInfo(os="mac", gpu_vendor=vendor, cuda_version=cuda, vram_gb=vram, arch=arch)

    # Linux or WSL2
    os_type = "wsl2" if _is_wsl2() else "linux"
    vendor, cuda, vram = _detect_gpu_linux()
    return PlatformInfo(
        os=os_type,
        gpu_vendor=vendor,
        cuda_version=cuda,
        vram_gb=vram,
        arch=arch,
    )
