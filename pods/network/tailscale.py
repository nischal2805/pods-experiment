import json
import re
import subprocess
from dataclasses import dataclass, field

from ..errors import NetworkError


@dataclass
class TailscaleStatus:
    running: bool
    peers: list[dict] = field(default_factory=list)


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def get_ip() -> str:
    result = _run(["tailscale", "ip", "-4"], timeout=10)
    if result is None:
        raise NetworkError(
            "Cannot get Tailscale IP",
            reason="tailscale CLI not found or not responding",
            suggestion="Install Tailscale from https://tailscale.com/download and run 'tailscale up'",
        )
    if result.returncode != 0 or not result.stdout.strip():
        raise NetworkError(
            "Cannot get Tailscale IP",
            reason=result.stderr.strip() or "tailscale ip returned empty output",
            suggestion="Run 'tailscale up' to connect to the Tailscale network",
        )
    return result.stdout.strip()


def get_status() -> TailscaleStatus:
    result = _run(["tailscale", "status", "--json"], timeout=10)
    if result is None or result.returncode != 0:
        return TailscaleStatus(running=False)
    try:
        data = json.loads(result.stdout)
        peers = list(data.get("Peer", {}).values())
        return TailscaleStatus(running=True, peers=peers)
    except json.JSONDecodeError:
        return TailscaleStatus(running=False)


def ping(peer_ip: str) -> dict:
    result = _run(["tailscale", "ping", peer_ip], timeout=15)
    if result is None:
        return {"ip": peer_ip, "direct": False, "derp_region": None, "output": "tailscale ping failed or timed out"}
    out = result.stdout
    direct = "direct connection" in out.lower()
    derp_region = None
    if not direct:
        # parse "via DERP(<region>)" from output
        m = re.search(r"via DERP\(([^)]+)\)", out)
        if m:
            derp_region = m.group(1)
    return {
        "ip": peer_ip,
        "direct": direct,
        "derp_region": derp_region,
        "output": out.strip(),
    }


def bring_up(authkey: str) -> None:
    result = _run(["tailscale", "up", f"--authkey={authkey}", "--accept-routes"], timeout=60)
    if result is None:
        raise NetworkError(
            "Failed to bring up Tailscale",
            reason="tailscale CLI not found or timed out",
            suggestion="Install Tailscale from https://tailscale.com/download",
        )
    if result.returncode != 0:
        raise NetworkError(
            "Failed to bring up Tailscale",
            reason=result.stderr.strip(),
            suggestion="Check that the auth key is valid and not expired",
        )
