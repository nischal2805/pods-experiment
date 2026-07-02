#!/usr/bin/env bash
set -euo pipefail

PODS_GITHUB="https://github.com/nischal2805/pods-experiment"
INSTALL_BIN="${HOME}/.local/bin"
VENV_DIR="${HOME}/.pods-venv"
PYTHON_VERSION="3.11"

# Support both: bash install.sh (from cloned repo) and curl | bash
_PIPED=0
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "/dev/stdin" && -f "$(dirname "${BASH_SOURCE[0]}")/pyproject.toml" ]]; then
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    _PIPED=1
    REPO_DIR="${HOME}/.pods-src"
    if [[ ! -d "${REPO_DIR}/.git" ]]; then
        echo "[pods] Cloning pods repository..."
        git clone "${PODS_GITHUB}" "${REPO_DIR}"
    else
        echo "[pods] Updating existing clone at ${REPO_DIR}..."
        git -C "${REPO_DIR}" pull --ff-only
    fi
    exec bash "${REPO_DIR}/install.sh"
fi

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

info()  { echo -e "${BOLD}[pods]${RESET} $*"; }
ok()    { echo -e "${GREEN}  [OK]${RESET}   $*"; }
warn()  { echo -e "${YELLOW}  [WARN]${RESET} $*"; }
fail()  { echo -e "${RED}  [FAIL]${RESET} $*"; }

# Detect OS
OS="linux"
if [[ "$(uname -s)" == "Darwin" ]]; then
    OS="mac"
elif grep -qi microsoft /proc/version 2>/dev/null; then
    OS="wsl2"
fi
info "Detected platform: ${OS}"

# Install uv if missing
if ! command -v uv &>/dev/null; then
    info "Installing uv (fast Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
    if ! command -v uv &>/dev/null; then
        fail "uv install failed. See https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
fi
ok "uv: $(uv --version)"

# uv handles Python download + venv creation in one step
if [[ ! -d "${VENV_DIR}" ]]; then
    info "Creating venv at ${VENV_DIR} with Python ${PYTHON_VERSION}..."
    uv venv --python "${PYTHON_VERSION}" "${VENV_DIR}"
else
    ok "Venv exists: ${VENV_DIR}"
fi
VENV_PYTHON="${VENV_DIR}/bin/python"
ok "Python: $("${VENV_PYTHON}" --version)"

# Tailscale
if ! command -v tailscale &>/dev/null; then
    info "Installing Tailscale..."
    if [[ "$OS" == "mac" ]]; then
        warn "Install Tailscale from https://tailscale.com/download/mac then rerun."
        warn "(Or: brew install --cask tailscale)"
    else
        curl -fsSL https://tailscale.com/install.sh | sh
    fi
else
    ok "Tailscale: $(tailscale version 2>/dev/null | head -1 || echo 'installed')"
fi

# Install pods (uv pip is much faster than pip)
info "Installing pods Python package..."
uv pip install --python "${VENV_PYTHON}" --quiet --reinstall --config-setting editable_mode=compat -e "${REPO_DIR}"
ok "pods package installed"

# Launcher
mkdir -p "${INSTALL_BIN}"
LAUNCHER="${INSTALL_BIN}/pods"
cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
# -P disables prepending CWD to sys.path, preventing collisions with
# user directories named "pods" (e.g. ~/pods/ holding llama.cpp).
# PYTHONSAFEPATH covers older 3.11 fallback if -P unsupported.
exec env PYTHONSAFEPATH=1 "${VENV_PYTHON}" -P -m pods "\$@"
EOF
chmod +x "${LAUNCHER}"
ok "Launcher at ${LAUNCHER}"

if [[ ":$PATH:" != *":${INSTALL_BIN}:"* ]]; then
    warn "Add this to your shell profile (~/.bashrc or ~/.zshrc):"
    echo ""
    echo "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
    echo ""
fi

# llama.cpp — build from source (reliable across release-naming changes)
LLAMA_SRC_DIR="${HOME}/pods/llama.cpp"
LLAMA_BIN_DIR="${LLAMA_SRC_DIR}/build/bin"
LLAMA_SERVER="${LLAMA_BIN_DIR}/llama-server"
RPC_SERVER="${LLAMA_BIN_DIR}/rpc-server"
LLAMA_REPO="https://github.com/ggerganov/llama.cpp"

if [[ -x "${LLAMA_SERVER}" && -x "${RPC_SERVER}" ]]; then
    ok "llama.cpp binaries already present at ${LLAMA_BIN_DIR}"
else
    info "Building llama.cpp from source (this takes 10-20 minutes)..."

    # Verify build deps
    MISSING=()
    command -v cmake &>/dev/null || MISSING+=("cmake")
    command -v g++ &>/dev/null || command -v clang++ &>/dev/null || MISSING+=("g++ or clang++")
    command -v git &>/dev/null || MISSING+=("git")
    if [[ ${#MISSING[@]} -gt 0 ]]; then
        fail "Missing build tools: ${MISSING[*]}"
        echo "    Install with: sudo apt install -y build-essential cmake git    (Debian/Ubuntu)"
        echo "                  sudo dnf install -y gcc-c++ cmake git              (Fedora/RHEL)"
        echo "                  brew install cmake                                  (macOS)"
        exit 1
    fi

    # Clone or update
    mkdir -p "${HOME}/pods"
    if [[ -d "${LLAMA_SRC_DIR}/.git" ]]; then
        info "Updating existing clone at ${LLAMA_SRC_DIR}..."
        git -C "${LLAMA_SRC_DIR}" pull --ff-only || warn "git pull failed — continuing with current checkout"
    else
        info "Cloning llama.cpp into ${LLAMA_SRC_DIR}..."
        git clone --depth 1 "${LLAMA_REPO}" "${LLAMA_SRC_DIR}"
    fi

    # Pick GPU backend flags
    CMAKE_FLAGS=("-DGGML_RPC=ON" "-DCMAKE_BUILD_TYPE=Release")
    if [[ "$OS" == "mac" ]]; then
        ok "Building with Metal (default on macOS)"
        # Metal is on by default on Apple Silicon — no flag needed
    elif command -v nvidia-smi &>/dev/null; then
        ok "Building with CUDA (nvidia-smi detected)"
        CMAKE_FLAGS+=("-DGGML_CUDA=ON")
    elif command -v rocm-smi &>/dev/null; then
        ok "Building with ROCm/HIP (rocm-smi detected)"
        CMAKE_FLAGS+=("-DGGML_HIP=ON")
    else
        warn "No GPU detected — building CPU-only"
    fi

    # Configure + build
    info "Running cmake configure..."
    if ! cmake -S "${LLAMA_SRC_DIR}" -B "${LLAMA_SRC_DIR}/build" "${CMAKE_FLAGS[@]}"; then
        fail "cmake configure failed. See output above."
        exit 1
    fi

    JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
    info "Compiling with ${JOBS} jobs (grab a coffee)..."
    # Upstream renamed the RPC target: rpc-server -> ggml-rpc-server (2026).
    # Try the new name first, fall back to the old one for older checkouts.
    if ! cmake --build "${LLAMA_SRC_DIR}/build" --config Release -j "${JOBS}" --target llama-server ggml-rpc-server; then
        warn "ggml-rpc-server target not found — retrying with legacy rpc-server target..."
        if ! cmake --build "${LLAMA_SRC_DIR}/build" --config Release -j "${JOBS}" --target llama-server rpc-server; then
            fail "cmake build failed. See output above."
            exit 1
        fi
    fi

    # Normalize binary name so pods always finds build/bin/rpc-server
    if [[ ! -x "${RPC_SERVER}" && -x "${LLAMA_BIN_DIR}/ggml-rpc-server" ]]; then
        ln -sf "ggml-rpc-server" "${RPC_SERVER}"
    fi

    if [[ -x "${LLAMA_SERVER}" && -x "${RPC_SERVER}" ]]; then
        ok "Built llama-server and rpc-server at ${LLAMA_BIN_DIR}"
    else
        fail "Build completed but binaries not found at expected paths."
        echo "    Expected: ${LLAMA_SERVER}"
        echo "    Expected: ${RPC_SERVER}"
        exit 1
    fi
fi

# Done
echo ""
echo -e "${BOLD}============================================${RESET}"
echo -e "${GREEN}${BOLD}  Pods installed successfully!${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo ""
echo "  Next steps:"
echo ""
echo "  On the COORDINATOR machine:"
echo "    pods init <pod-name>"
echo "    pods keygen my-api-key"
echo "    pods invite                            # prints invite link"
echo ""
echo "  On each WORKER machine:"
echo "    pods join <invite-link> --authkey <tailscale-auth-key>"
echo "    pods attach"
echo ""
echo "  Load a model and start inferencing:"
echo "    pods model add qwen0.5b       # smallest, ~400MB"
echo "    pods model load qwen0.5b      # auto-discovers workers"
echo ""
echo "  OpenAI-compatible API:  http://localhost:8080/v1/chat/completions"
echo "  Live dashboard:         http://localhost:8080/dashboard"
echo ""
echo "  Tailscale auth key:     https://login.tailscale.com/admin/settings/keys"
echo "  Cleanup script:         bash ~/.pods-src/uninstall.sh"
echo ""
