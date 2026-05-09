#!/usr/bin/env bash
set -euo pipefail

PODS_GITHUB="https://github.com/nischal2805/pods-experiment"
INSTALL_BIN="${HOME}/.local/bin"

# Support both: bash install.sh (from cloned repo) and curl | bash
_PIPED=0
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "/dev/stdin" && -f "$(dirname "${BASH_SOURCE[0]}")/pyproject.toml" ]]; then
    REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
    _PIPED=1
    REPO_DIR="${HOME}/.pods-src"
    if [[ ! -d "${REPO_DIR}/.git" ]]; then
        echo "[pods] Cloning pods repository..."
        git clone --depth=1 "${PODS_GITHUB}" "${REPO_DIR}"
    else
        echo "[pods] Updating existing clone at ${REPO_DIR}..."
        git -C "${REPO_DIR}" pull --ff-only
    fi
    # Re-exec from fresh clone so cached curl response never runs stale code
    exec bash "${REPO_DIR}/install.sh"
fi
BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

info()  { echo -e "${BOLD}[pods]${RESET} $*"; }
ok()    { echo -e "${GREEN}  ✓${RESET} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${RESET} $*"; }

# ── Detect OS ──────────────────────────────────────────────────────────────
OS="linux"
if [[ "$(uname -s)" == "Darwin" ]]; then
    OS="mac"
elif grep -qi microsoft /proc/version 2>/dev/null; then
    OS="wsl2"
fi
info "Detected platform: ${OS}"

# ── Python 3.11+ ────────────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info >= (3,11))" 2>/dev/null || echo "False")
        if [[ "$VER" == "True" ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    info "Installing Python 3.11..."
    if [[ "$OS" == "mac" ]]; then
        if ! command -v brew &>/dev/null; then
            warn "Homebrew not found. Install from https://brew.sh then rerun this script."
            exit 1
        fi
        brew install python@3.11
        PYTHON="python3.11"
    else
        sudo apt-get update -qq
        sudo apt-get install -y software-properties-common
        sudo add-apt-repository -y ppa:deadsnakes/ppa
        sudo apt-get install -y python3.11 python3.11-venv python3-pip
        PYTHON="python3.11"
    fi
fi
ok "Python: $($PYTHON --version)"

# ── venv (avoids PEP 668 externally-managed-environment error) ───────────────
VENV_DIR="${HOME}/.pods-venv"
if [[ ! -d "${VENV_DIR}" ]]; then
    info "Creating venv at ${VENV_DIR}..."
    # python3-venv may not be installed
    if ! "$PYTHON" -m venv --help &>/dev/null 2>&1; then
        if [[ "$OS" == "mac" ]]; then
            warn "python3-venv missing. Run: brew install python@3.11"
            exit 1
        else
            sudo apt-get install -y "$(basename "$PYTHON")-venv" 2>/dev/null \
                || sudo apt-get install -y python3-venv
        fi
    fi
    "$PYTHON" -m venv "${VENV_DIR}"
fi
VENV_PYTHON="${VENV_DIR}/bin/python"
VENV_PIP="${VENV_DIR}/bin/pip"
ok "Venv: ${VENV_DIR}"

# ── Tailscale ───────────────────────────────────────────────────────────────
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

# ── Install pods into venv ───────────────────────────────────────────────────
info "Installing pods Python package..."
"$VENV_PIP" install --quiet -e "${REPO_DIR}"
ok "pods package installed"

# ── PATH setup ───────────────────────────────────────────────────────────────
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

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}${BOLD}  Pods installed successfully!${RESET}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
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
echo "    pods model add qwen7b        # download ~5GB"
echo "    pods model load qwen7b       # auto-starts workers"
echo ""
echo "  Then use the OpenAI-compatible API at http://localhost:8080"
echo ""
echo "  Get a Tailscale auth key at: https://login.tailscale.com/admin/settings/keys"
echo ""
