import json
import subprocess
from dataclasses import dataclass, field

from ..errors import NetworkError


@dataclass
class TailscaleStatus:
    running: bool
    peers: list[dict] = field(default_factory=list)


def get_ip() -> str:
    result = subprocess.run(
        ["tailscale", "ip", "-4"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise NetworkError(
            "Cannot get Tailscale IP",
            reason=result.stderr.strip() or "tailscale ip returned empty output",
            suggestion="Run 'tailscale up' to connect to the Tailscale network",
        )
    return result.stdout.strip()


def get_status() -> TailscaleStatus:
    result = subprocess.run(
        ["tailscale", "status", "--json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return TailscaleStatus(running=False)
    try:
        data = json.loads(result.stdout)
        peers = list(data.get("Peer", {}).values())
        return TailscaleStatus(running=True, peers=peers)
    except json.JSONDecodeError:
        return TailscaleStatus(running=False)


def ping(peer_ip: str) -> dict:
    result = subprocess.run(
        ["tailscale", "ping", peer_ip],
        capture_output=True,
        text=True,
        timeout=15,
    )
    out = result.stdout
    direct = "direct connection" in out.lower()
    derp_region = None
    if not direct:
        # parse "via DERP(<region>)" from output
        import re
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
    result = subprocess.run(
        ["tailscale", "up", f"--authkey={authkey}", "--accept-routes"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise NetworkError(
            "Failed to bring up Tailscale",
            reason=result.stderr.strip(),
            suggestion="Check that the auth key is valid and not expired",
        )
