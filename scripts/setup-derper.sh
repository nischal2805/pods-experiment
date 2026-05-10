#!/usr/bin/env bash
# Setup script for custom Tailscale DERP relay on Ubuntu 24.04 droplet.
# Usage: DERP_DOMAIN=derp.example.com ./setup-derper.sh
#
# Idempotent — safe to re-run.

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root" >&2
    exit 1
fi

if [[ -z "${DERP_DOMAIN:-}" ]]; then
    echo "Set DERP_DOMAIN env var (e.g., DERP_DOMAIN=derp.example.com)" >&2
    exit 1
fi

GO_VERSION="1.23.4"
DERP_USER="derper"
DERP_HOME="/var/lib/derper"
GO_BIN="/usr/local/go/bin/go"

echo "[derper-setup] Updating apt..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates ufw

echo "[derper-setup] Installing Go ${GO_VERSION}..."
if [[ ! -x "${GO_BIN}" ]] || ! "${GO_BIN}" version | grep -q "go${GO_VERSION}"; then
    cd /tmp
    curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz" -o go.tar.gz
    rm -rf /usr/local/go
    tar -C /usr/local -xzf go.tar.gz
    rm go.tar.gz
fi
"${GO_BIN}" version

echo "[derper-setup] Creating ${DERP_USER} user + dirs..."
if ! id "${DERP_USER}" &>/dev/null; then
    useradd --system --home "${DERP_HOME}" --shell /usr/sbin/nologin "${DERP_USER}"
fi
mkdir -p "${DERP_HOME}"
chown -R "${DERP_USER}:${DERP_USER}" "${DERP_HOME}"

echo "[derper-setup] Building derper from tailscale source..."
sudo -u "${DERP_USER}" -H bash -c "
    export PATH=/usr/local/go/bin:\$PATH
    export GOPATH=${DERP_HOME}/go
    export GOBIN=${DERP_HOME}/bin
    mkdir -p \$GOPATH \$GOBIN
    /usr/local/go/bin/go install tailscale.com/cmd/derper@latest
    /usr/local/go/bin/go install tailscale.com/cmd/stunc@latest || true
"

DERPER_BIN="${DERP_HOME}/bin/derper"
if [[ ! -x "${DERPER_BIN}" ]]; then
    echo "derper build failed — binary not found at ${DERPER_BIN}" >&2
    exit 1
fi

echo "[derper-setup] Configuring firewall..."
ufw --force enable
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 3478/udp
ufw reload

echo "[derper-setup] Writing systemd unit..."
cat > /etc/systemd/system/derper.service <<EOF
[Unit]
Description=Tailscale DERP relay
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${DERP_USER}
Group=${DERP_USER}
ExecStart=${DERPER_BIN} \\
    --hostname=${DERP_DOMAIN} \\
    --certmode=letsencrypt \\
    --certdir=${DERP_HOME}/certs \\
    --a=:443 \\
    --http-port=80 \\
    --stun \\
    --verify-clients=false
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${DERP_HOME}

[Install]
WantedBy=multi-user.target
EOF

mkdir -p "${DERP_HOME}/certs"
chown -R "${DERP_USER}:${DERP_USER}" "${DERP_HOME}"

systemctl daemon-reload
systemctl enable derper
systemctl restart derper

echo "[derper-setup] Waiting 5s for derper to start..."
sleep 5
if ! systemctl is-active --quiet derper; then
    echo "derper failed to start. Logs:" >&2
    journalctl -u derper -n 50 --no-pager
    exit 1
fi

echo ""
echo "[derper-setup] Done."
echo ""
echo "Verify:"
echo "  curl -v https://${DERP_DOMAIN}/"
echo "  systemctl status derper"
echo "  journalctl -u derper -f"
echo ""
echo "Next: register this DERP in tailnet ACL — see docs/CUSTOM_DERP.md step 4."
