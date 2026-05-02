import sys
import json
import subprocess
from pathlib import Path

import click
import httpx

from ..errors import PodsError
from ..network.invite import decode_invite
from ..network.tailscale import bring_up, get_ip
from ..internal_auth import HEADER_NAME
from ..platform.detect import detect_platform
from ..platform.setup import validate_existing_binaries, download_and_install_binaries
from ..preflight import PreflightChecker
from ..state.defaults import new_member

CONFIG_PATH = Path.home() / ".pods" / "config.json"
LOGS_DIR = Path.home() / ".pods" / "logs"


@click.command()
@click.argument("link")
@click.option("--authkey", required=True, help="Tailscale pre-auth key from admin.tailscale.com")
def cmd(link: str, authkey: str):
    """Join an existing pod using an invite link."""
    try:
        invite = decode_invite(link)
        coordinator_ip = invite["coordinator_ip"]
        internal_token = invite["internal_token"]

        click.echo(f"Joining pod '{invite.get('pod_name', 'unknown')}'...")
        click.echo("Connecting to Tailscale...")
        bring_up(authkey)

        tailscale_ip = get_ip()

        click.echo("Running pre-flight checks...")
        results = PreflightChecker().run()
        if any(r.status == "block" for r in results):
            click.echo("Pre-flight checks failed.")
            sys.exit(1)

        click.echo("Checking llama.cpp binaries...")
        try:
            validate_existing_binaries()
        except PodsError:
            platform_info = detect_platform()
            download_and_install_binaries(platform_info)

        platform_info = detect_platform()
        existing_node_id = None
        try:
            existing = json.loads(CONFIG_PATH.read_text())
            if existing.get("coordinator_ip") == coordinator_ip and existing.get("role") == "worker":
                existing_node_id = existing.get("node_id")
        except Exception:
            pass
        member = new_member(
            name=tailscale_ip,
            tailscale_ip=tailscale_ip,
            role="worker",
            os=platform_info.os,
            gpu_vram_gb=platform_info.vram_gb,
        )
        if existing_node_id:
            member.node_id = existing_node_id

        try:
            r = httpx.post(
                f"http://{coordinator_ip}:8080/internal/register",
                json={
                    "node_id": member.node_id,
                    "name": member.name,
                    "tailscale_ip": tailscale_ip,
                    "role": "worker",
                    "os": platform_info.os,
                    "gpu_vram_gb": platform_info.vram_gb,
                },
                headers={HEADER_NAME: internal_token},
                timeout=10,
            )
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise PodsError(
                "Coordinator rejected registration",
                reason=f"HTTP {e.response.status_code}",
                suggestion=f"Ensure coordinator at {coordinator_ip} is running 'pods init'",
            )
        except httpx.RequestError as e:
            raise PodsError(
                "Cannot reach coordinator",
                reason=str(e),
                suggestion=f"Check coordinator at {coordinator_ip} is online and reachable via Tailscale",
            )

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        config = {
            "coordinator_ip": coordinator_ip,
            "node_id": member.node_id,
            "role": "worker",
            "internal_token": internal_token,
        }
        CONFIG_PATH.write_text(json.dumps(config, indent=2))

        log = open(LOGS_DIR / "agent.log", "a")
        subprocess.Popen(
            ["uvicorn", "pods.agent.server:app", "--host", "0.0.0.0", "--port", "8082", "--log-level", "warning"],
            stdout=log, stderr=log,
        )

        click.echo(f"\n✓ Joined pod. Node IP: {tailscale_ip}")
        click.echo("  Run 'pods attach' to start inference backend.")

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
