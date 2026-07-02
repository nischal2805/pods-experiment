# Custom DERP Relay for Pods

## Why

Default tailscale DERP servers are public. Latency to nearest (Bengaluru) ≈ 93ms.
When UDP holepunch fails (CGNAT, wifi NAT churn, WSL2 quirks), tailscale falls back to
DERP relay. Public DERP at ~100ms RTT is too slow + unstable for llama.cpp RPC tensor
traffic — connections drop mid-handshake (`Accepted client connection / Client connection closed`).

Solution: run our own DERP server on a DigitalOcean droplet in the same region (Bengaluru,
~1-5ms latency). Tailscale prefers our DERP automatically. RPC over our DERP is stable
even when direct path fails.

This does NOT replace tailscale. Pods still uses 100.x.x.x IPs exclusively per spec.
Only the relay infrastructure changes.

## Cost

- DO droplet: $6/mo (Basic, 1 vCPU, 1GB RAM, BLR1 region)
- Bandwidth: 1TB included, plenty for relay traffic

## Prerequisites

- DigitalOcean account with credits
- Domain name (or use DO's default droplet hostname)
- Tailscale tailnet admin access
- `derper` requires HTTPS — needs a domain pointing at droplet IP

## Setup

### 1. Spin DO droplet

- Region: **BLR1** (Bengaluru) — closest to home boxes
- Image: Ubuntu 24.04 LTS
- Size: Basic / Regular / 1 vCPU / 1GB RAM ($6/mo)
- Authentication: SSH key
- Hostname: `pods-derp-blr`

Note the public IPv4. Add firewall rules (DO control panel or `ufw`):
- TCP 22 (SSH, your IP only)
- TCP 80 (Let's Encrypt HTTP-01 challenge)
- TCP 443 (DERP HTTPS)
- UDP 3478 (STUN)

### 2. Point domain at droplet

Add A record: `derp.yourdomain.com` → droplet public IP.
Wait for DNS propagation (`dig derp.yourdomain.com`).

### 3. Run setup script on droplet

```bash
ssh root@<droplet-ip>
curl -fsSL https://raw.githubusercontent.com/nischal2805/pods-experiment/feat/custom-derp-relay/scripts/setup-derper.sh -o setup.sh
chmod +x setup.sh
DERP_DOMAIN=derp.yourdomain.com ./setup.sh
```

Script installs Go, builds `derper` from tailscale source, sets up systemd unit + Let's Encrypt
cert, opens firewall. Verify:

```bash
systemctl status derper
journalctl -u derper -n 50
curl https://derp.yourdomain.com/   # should return DERP banner
```

### 4. Register custom DERP in tailnet ACL

Open https://login.tailscale.com/admin/acls. Edit policy file. Add `derpMap`:

```json
{
  "derpMap": {
    "OmitDefaultRegions": false,
    "Regions": {
      "900": {
        "RegionID": 900,
        "RegionCode": "podsblr",
        "RegionName": "Pods Bengaluru",
        "Nodes": [
          {
            "Name": "1",
            "RegionID": 900,
            "HostName": "derp.yourdomain.com",
            "IPv4": "<droplet-public-ip>"
          }
        ]
      }
    }
  },
  "acls": [ /* your existing ACLs */ ]
}
```

Region ID must be ≥ 900 (custom range). `OmitDefaultRegions: false` keeps fallback to public DERPs.

Save policy. Tailscale clients pick up new DERP map within ~60s.

### 5. Verify on home boxes

```bash
tailscale netcheck
# Look for "podsblr" in DERP latency list — should be 1-10ms
tailscale debug derp-map | jq '.Regions["900"]'
tailscale ping -c 5 <peer-tailscale-ip>
# Path should be either "direct" or "via DERP(podsblr)"
# NOT "via DERP(blr)" — that means public DERP, our DERP not active
```

If still routing via public DERP: check droplet firewall (port 443 open?), DNS resolves,
TLS cert valid (`curl -v https://derp.yourdomain.com/`).

### 6. Retry RPC load

```bash
# boss (coordinator)
pods model unload qwen0.5b   # if loaded
pods model load qwen0.5b     # with RPC
```

llama-server health should now pass even when direct path drops to relay, because relay
is now <10ms instead of 100ms+.

## Operational Notes

- DERP runs as systemd unit `derper.service`. Restart: `systemctl restart derper`.
- Logs: `journalctl -u derper -f`.
- Cert renewal: derper handles Let's Encrypt auto-renewal internally. No cron needed.
- Bandwidth monitoring: DO control panel or `vnstat` on droplet.
- If droplet dies: tailscale falls back to public DERPs automatically. No outage of pods,
  just slower relay until droplet returns.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `tailscale netcheck` doesn't list podsblr | ACL `derpMap` saved? Wait 60s. `tailscale debug prefs` |
| `podsblr` listed but very slow | DO droplet under load? Check `top` on droplet |
| Cert errors in derper logs | Domain DNS correct? Port 80/443 open? Let's Encrypt rate limits hit? |
| Still routing via `blr` (public) | Custom DERP must have lower latency. If droplet >50ms, public wins. Check `tailscale ping --tsmp` |

## Rollback

Remove `derpMap` block from tailnet ACL. Tailscale reverts to public DERPs within 60s.
Destroy droplet in DO panel.
