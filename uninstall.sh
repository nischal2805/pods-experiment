#!/usr/bin/env bash
# Pods full uninstaller. Removes venv, binaries, state, models, launcher.
# Tailscale is NOT removed (independent tool, may be used elsewhere).
set -uo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"

info()  { echo -e "${BOLD}[pods]${RESET} $*"; }
ok()    { echo -e "${GREEN}  [OK]${RESET}   $*"; }
warn()  { echo -e "${YELLOW}  [WARN]${RESET} $*"; }

YES=0
KEEP_MODELS=0
for arg in "$@"; do
    case "$arg" in
        --yes|-y) YES=1 ;;
        --keep-models) KEEP_MODELS=1 ;;
        *) warn "Unknown arg: $arg" ;;
    esac
done

info "Pods uninstall plan:"
echo "    - Stop running gateway / agent / llama-server / rpc-server processes"
echo "    - Remove ~/.pods/                  (state.json, config.json, logs)"
echo "    - Remove ~/.pods-venv/             (Python venv)"
echo "    - Remove ~/.pods-src/              (cloned source, if any)"
echo "    - Remove ~/.local/bin/pods         (launcher)"
if [[ "${KEEP_MODELS}" -eq 0 ]]; then
    echo "    - Remove ~/pods/                   (llama.cpp binaries + models)"
else
    echo "    - Keep   ~/pods/models/            (--keep-models)"
    echo "    - Remove ~/pods/llama.cpp/         (binaries only)"
fi
echo ""

if [[ "${YES}" -eq 0 ]]; then
    read -r -p "Proceed? [y/N] " ans
    [[ "${ans}" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

info "Stopping pods processes..."
# Best-effort. pkill returns nonzero if nothing matched — fine.
pkill -f "uvicorn pods.gateway" 2>/dev/null && ok "stopped gateway" || warn "gateway not running"
pkill -f "uvicorn pods.agent"   2>/dev/null && ok "stopped agent"   || warn "agent not running"
pkill -f "llama-server"         2>/dev/null && ok "stopped llama-server" || true
pkill -f "rpc-server"           2>/dev/null && ok "stopped rpc-server"   || true
sleep 1

remove() {
    if [[ -e "$1" ]]; then
        rm -rf "$1" && ok "removed $1"
    else
        warn "$1 (not present)"
    fi
}

remove "${HOME}/.pods"
remove "${HOME}/.pods-venv"
remove "${HOME}/.pods-src"
remove "${HOME}/.local/bin/pods"

if [[ "${KEEP_MODELS}" -eq 0 ]]; then
    remove "${HOME}/pods"
else
    remove "${HOME}/pods/llama.cpp"
fi

echo ""
echo -e "${GREEN}${BOLD}  Pods uninstalled.${RESET}"
echo ""
echo "  Tailscale was NOT removed. To leave Tailscale:"
echo "    sudo tailscale logout && sudo tailscale down"
echo ""
echo "  uv was NOT removed. To uninstall uv:"
echo "    uv self uninstall"
echo ""
