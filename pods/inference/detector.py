from ..platform.detect import PlatformInfo


def viable_engines(platform_info: PlatformInfo) -> list[str]:
    """Return engine names viable on this platform, in priority order.

    Order: llamacpp (if NVIDIA/AMD on Linux/WSL2) → exo (Linux/Mac) → ollama (always).
    Apple Silicon puts exo first due to MLX optimization.
    Windows gets ollama only.
    """
    if platform_info.os == "windows":
        return ["ollama"]

    engines: list[str] = []

    if platform_info.gpu_vendor == "apple":
        engines.append("exo")
        engines.append("llamacpp")
    elif platform_info.gpu_vendor in ("nvidia", "amd") and platform_info.os in ("linux", "wsl2"):
        engines.append("llamacpp")
        if platform_info.os == "linux":
            engines.append("exo")
    else:
        # CPU-only Linux or Mac Intel
        if platform_info.os in ("linux", "mac"):
            engines.append("exo")

    engines.append("ollama")
    return engines
