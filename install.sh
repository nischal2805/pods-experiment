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
uv pip install --python "${VENV_PYTHON}" --quiet --reinstall -e "${REPO_DIR}"
ok "pods package installed"

# Launcher
mkdir -p "${INSTALL_BIN}"
LAUNCHER="${INSTALL_BIN}/pods"
cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
exec "${VENV_PYTHON}" -m pods "\$@"
EOF
chmod +x "${LAUNCHER}"
ok "Launcher at ${LAUNCHER}"

if [[ ":$PATH:" != *":${INSTALL_BIN}:"* ]]; then
    warn "Add this to your shell profile (~/.bashrc or ~/.zshrc):"
    echo ""
    echo "  export PATH=\"\${HOME}/.local/bin:\${PATH}\""
    echo ""
fi

# llama.cpp prebuilt binaries
LLAMA_BIN_DIR="${HOME}/pods/llama.cpp/build/bin"
LLAMA_SERVER="${LLAMA_BIN_DIR}/llama-server"
RPC_SERVER="${LLAMA_BIN_DIR}/rpc-server"

if [[ -x "${LLAMA_SERVER}" && -x "${RPC_SERVER}" ]]; then
    ok "llama.cpp binaries already present at ${LLAMA_BIN_DIR}"
else
    info "Downloading prebuilt llama.cpp binaries (auto-detect CUDA/Metal/ROCm)..."
    if "${VENV_PYTHON}" -c "
from pods.platform.detect import detect_platform
from pods.platform.setup import download_and_install_binaries
download_and_install_binaries(detect_platform())
"; then
        ok "llama.cpp binaries installed"
    else
        warn "Prebuilt download failed. Build manually:"
        echo "    git clone https://github.com/ggerganov/llama.cpp ~/pods/llama.cpp"
        echo "    cd ~/pods/llama.cpp && cmake -B build -DGGML_RPC=ON -DGGML_CUDA=ON"
        echo "    cmake --build build --config Release -j"
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
