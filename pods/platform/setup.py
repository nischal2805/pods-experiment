from pathlib import Path

from ..errors import PlatformError
from .detect import PlatformInfo

LLAMA_BIN_DIR = Path.home() / "pods" / "llama.cpp" / "build" / "bin"
LLAMA_SERVER = LLAMA_BIN_DIR / "llama-server"
RPC_SERVER = LLAMA_BIN_DIR / "rpc-server"


def validate_existing_binaries() -> None:
    """Check that llama-server and rpc-server exist and are executable.

    Raises PlatformError with the exact missing path if either check fails.
    """
    for binary in [LLAMA_SERVER, RPC_SERVER]:
        if not binary.exists():
            raise PlatformError(
                f"Binary not found: {binary}",
                reason=f"Expected at {binary}",
                suggestion="Run 'pods init' to download llama.cpp binaries for your platform",
            )
        if not (binary.stat().st_mode & 0o111):
            raise PlatformError(
                f"Binary not executable: {binary}",
                reason="File exists but has no execute permission",
                suggestion=f"Run: chmod +x {binary}",
            )


def download_and_install_binaries(platform_info: PlatformInfo) -> None:
    """Download and install llama.cpp binaries for the detected platform.

    Only downloads if binaries are not already present (calls validate_existing_binaries
    first and skips if they pass). Supports linux-cuda12, linux-cuda11, linux-rocm,
    linux-cpu, macos-metal-arm64, macos-cpu-x86.

    Implemented in Phase 2.
    """
    raise NotImplementedError("Binary download implemented in Phase 2")
