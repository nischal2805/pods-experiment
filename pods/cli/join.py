import sys
import json
import subprocess
from pathlib import Path

import click
import httpx

from ..errors import PodsError
from ..network.invite import decode_invite
from ..network.tailscale import bring_up, get_ip
from ..platform.detect import detect_platform
from ..platform.setup import validate_existing_binaries, download_and_install_binaries
from ..preflight import PreflightChecker
from ..state.defaults import new_member

CONFIG_PATH = Path.home() / ".pods" / "config.json"
LOGS_DIR = Path.home() / ".pods" / "logs"


@click.command()
@click.argument("link")
def cmd(link: str):
    """Join an existing pod using an invite link."""
    try:
        invite = decode_invite(link)
        coordinator_ip = invite["coordinator_ip"]
        authkey = invite["authkey"]

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
        member = new_member(
            name=tailscale_ip,
            tailscale_ip=tailscale_ip,
            role="worker",
            os=platform_info.os,
            gpu_vram_gb=platform_info.vram_gb,
        )

        httpx.post(
            f"http://{coordinator_ip}:8080/internal/register",
            json={
                "node_id": member.node_id,
                "name": member.name,
                "tailscale_ip": tailscale_ip,
                "role": "worker",
                "os": platform_info.os,
                "gpu_vram_gb": platform_info.vram_gb,
            },
            timeout=10,
        )

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        config = {"coordinator_ip": coordinator_ip, "node_id": member.node_id, "role": "worker"}
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
