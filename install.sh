#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_BIN="${HOME}/.local/bin"
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

# ── pip ──────────────────────────────────────────────────────────────────────
if ! "$PYTHON" -m pip --version &>/dev/null; then
    info "Installing pip..."
    curl -fsSL https://bootstrap.pypa.io/get-pip.py | "$PYTHON"
fi

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

# ── Install pods ─────────────────────────────────────────────────────────────
info "Installing pods Python package..."
"$PYTHON" -m pip install --quiet -e "${REPO_DIR}[dev]"
ok "pods package installed"

# ── PATH setup ───────────────────────────────────────────────────────────────
mkdir -p "${INSTALL_BIN}"

PODS_ENTRY=$(command -v pods 2>/dev/null || true)
if [[ -z "$PODS_ENTRY" ]]; then
    LAUNCHER="${INSTALL_BIN}/pods"
    cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
exec ${PYTHON} -m pods "\$@"
EOF
    chmod +x "${LAUNCHER}"
    ok "Created launcher at ${LAUNCHER}"
fi

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
echo "    pods invite --authkey <tailscale-auth-key>"
echo ""
echo "  On each WORKER machine:"
echo "    pods join <invite-link>"
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
