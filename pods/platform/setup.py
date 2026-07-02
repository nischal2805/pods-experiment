import json
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from ..errors import PlatformError
from .detect import PlatformInfo

LLAMA_BIN_DIR = Path.home() / "pods" / "llama.cpp" / "build" / "bin"
LLAMA_SERVER = LLAMA_BIN_DIR / "llama-server"
RPC_SERVER = LLAMA_BIN_DIR / "rpc-server"
GITHUB_API = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"


def validate_existing_binaries() -> None:
    for binary in [LLAMA_SERVER, RPC_SERVER]:
        if not binary.exists():
            raise PlatformError(
                f"Binary not found: {binary.name}",
                reason=f"Expected at {binary}",
                suggestion="Run 'pods init' to download llama.cpp binaries",
            )
        if not (binary.stat().st_mode & 0o111):
            raise PlatformError(
                f"Binary not executable: {binary.name}",
                reason="File exists but has no execute permission",
                suggestion=f"Run: chmod +x {binary}",
            )


def _asset_keywords(platform_info: PlatformInfo) -> list[str]:
    if platform_info.os in ("linux", "wsl2"):
        if platform_info.gpu_vendor == "nvidia":
            major = platform_info.cuda_version.split(".")[0] if platform_info.cuda_version else "12"
            return ["linux", "cuda", f"cu{major}", "x86_64"]
        elif platform_info.gpu_vendor == "amd":
            return ["linux", "rocm", "x86_64"]
        else:
            return ["linux", "cpu", "x86_64"]
    elif platform_info.os == "mac":
        arch = platform_info.arch if platform_info.arch else "arm64"
        return ["macos", arch]
    raise PlatformError(
        "Unsupported platform for binary download",
        reason=f"os={platform_info.os}",
        suggestion="Manually place llama-server and rpc-server at ~/pods/llama.cpp/build/bin/",
    )


def _find_asset(assets: list[dict], keywords: list[str]) -> str:
    """Find asset URL where all keywords appear in the asset name (case-insensitive).

    Tries progressively looser matches to handle llama.cpp naming variations
    (ubuntu vs linux, x64 vs x86_64, cu12 vs cuda, etc.).
    """
    zips = [a for a in assets if a["name"].lower().endswith(".zip")]

    # Each group: alternatives that satisfy the same requirement
    def _alternatives(k: str) -> tuple[str, ...]:
        if k in ("linux", "wsl2"):
            return ("linux", "ubuntu")
        if k == "x86_64":
            return ("x86_64", "x64")
        return (k,)

    def _matches(name: str, groups: list[tuple[str, ...]]) -> bool:
        return all(any(alt in name for alt in grp) for grp in groups)

    # Attempt 1: all keywords (with platform synonyms)
    groups = [_alternatives(k) for k in keywords]
    for asset in zips:
        if _matches(asset["name"].lower(), groups):
            return asset["browser_download_url"]

    # Attempt 2: drop cu<N> version specificity (keep "cuda")
    groups2 = [_alternatives(k) for k in keywords if not k.startswith("cu")]
    for asset in zips:
        if _matches(asset["name"].lower(), groups2):
            return asset["browser_download_url"]

    # Attempt 3: drop cuda requirement entirely (CPU build acceptable as last resort)
    groups3 = [_alternatives(k) for k in keywords if k not in ("cuda", "rocm") and not k.startswith("cu")]
    for asset in zips:
        if _matches(asset["name"].lower(), groups3):
            return asset["browser_download_url"]

    raise PlatformError(
        "No matching llama.cpp binary found for this platform",
        reason=f"Keywords: {keywords}",
        suggestion="Manually place llama-server and rpc-server at ~/pods/llama.cpp/build/bin/",
    )


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def download_and_install_binaries(platform_info: PlatformInfo) -> None:
    """Download correct llama.cpp pre-built binaries from GitHub releases."""
    # Platform guard first — raises PlatformError before any network I/O
    keywords = _asset_keywords(platform_info)

    print("Fetching latest llama.cpp release info...")
    try:
        req = urllib.request.Request(GITHUB_API, headers={"User-Agent": "pods-cli"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read())
    except Exception as e:
        raise PlatformError(
            "Failed to fetch llama.cpp release info",
            reason=str(e),
            suggestion="Check your internet connection",
        )

    tag = release["tag_name"]
    assets = release.get("assets", [])
    url = _find_asset(assets, keywords)

    print(f"Downloading llama.cpp {tag} ({', '.join(keywords)})...")
    LLAMA_BIN_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "llama.zip"
        try:
            urllib.request.urlretrieve(url, zip_path)
        except Exception as e:
            raise PlatformError(
                "Failed to download llama.cpp binaries",
                reason=str(e),
                suggestion=f"Try downloading manually from {url}",
            )

        print("Extracting binaries...")
        with zipfile.ZipFile(zip_path) as zf:
            extracted = []
            for name in zf.namelist():
                basename = Path(name).name
                if basename in ("llama-server", "rpc-server", "llama-server.exe", "rpc-server.exe"):
                    dest = LLAMA_BIN_DIR / basename
                    dest.write_bytes(zf.read(name))
                    _make_executable(dest)
                    extracted.append(basename)

            if not extracted:
                # Some releases use llama-rpc-server or ggml-rpc-server instead of rpc-server
                for name in zf.namelist():
                    basename = Path(name).name
                    if basename in ("llama-rpc-server", "llama-rpc-server.exe", "ggml-rpc-server", "ggml-rpc-server.exe"):
                        dest = LLAMA_BIN_DIR / "rpc-server"
                        dest.write_bytes(zf.read(name))
                        _make_executable(dest)
                        extracted.append("rpc-server (from llama-rpc-server)")
                    elif "llama-server" in basename and not basename.startswith("llama-server-"):
                        dest = LLAMA_BIN_DIR / "llama-server"
                        dest.write_bytes(zf.read(name))
                        _make_executable(dest)
                        extracted.append("llama-server")

    print(f"  ✓ Installed: {', '.join(extracted)}")
    print(f"  ✓ Location: {LLAMA_BIN_DIR}")

    validate_existing_binaries()
    print("  ✓ Binaries verified")
