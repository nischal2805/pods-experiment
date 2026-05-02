import sys
import json
import subprocess
from pathlib import Path

import click

from ..errors import PodsError
from ..network.tailscale import get_ip
from ..platform.detect import detect_platform
from ..platform.setup import validate_existing_binaries, download_and_install_binaries
from ..preflight import PreflightChecker
from ..state.defaults import new_member, new_pod
from ..state.schema import PodState
from ..state.store import StateStore

CONFIG_PATH = Path.home() / ".pods" / "config.json"
LOGS_DIR = Path.home() / ".pods" / "logs"


@click.command()
@click.argument("name")
def cmd(name: str):
    """Initialize a new pod on this coordinator machine."""
    try:
        click.echo("Running pre-flight checks...")
        checker = PreflightChecker()
        results = checker.run()
        if any(r.status == "block" for r in results):
            click.echo("Pre-flight checks failed. Fix the issues above and retry.")
            sys.exit(1)

        tailscale_ip = get_ip()

        click.echo("Checking llama.cpp binaries...")
        try:
            validate_existing_binaries()
            click.echo("  ✓ Binaries OK")
        except PodsError:
            platform_info = detect_platform()
            click.echo(f"  Downloading binaries for {platform_info.os}/{platform_info.gpu_vendor}...")
            download_and_install_binaries(platform_info)

        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        store = StateStore()
        pod = new_pod(name, tailscale_ip)
        member = new_member(
            name="coordinator",
            tailscale_ip=tailscale_ip,
            role="coordinator",
            os=detect_platform().os,
        )
        state = PodState(pod=pod, members=[member])
        store.save(state)

        config = {"coordinator_ip": tailscale_ip, "node_id": member.node_id, "role": "coordinator"}
        CONFIG_PATH.write_text(json.dumps(config, indent=2))

        log = open(LOGS_DIR / "gateway.log", "a")
        subprocess.Popen(
            ["uvicorn", "pods.gateway.app:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "warning"],
            stdout=log, stderr=log,
        )

        click.echo(f"\n✓ Pod '{name}' initialized.")
        click.echo(f"  Coordinator IP: {tailscale_ip}")
        click.echo(f"  Gateway running on port 8080")
        click.echo(f"  Run 'pods invite' to generate a join link for other machines.")

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
