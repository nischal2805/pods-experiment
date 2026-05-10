import sys
import json
from pathlib import Path

import click
import httpx

from ..errors import PodsError
from ..internal_auth import internal_headers

CONFIG_PATH = Path.home() / ".pods" / "config.json"


@click.command()
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.option("--keep-config", is_flag=True, help="Don't delete ~/.pods/config.json")
def cmd(yes: bool, keep_config: bool):
    """Leave the pod — notify coordinator, stop local agent + rpc-server."""
    try:
        if not CONFIG_PATH.exists():
            click.echo(f"No config at {CONFIG_PATH} — not joined to any pod.")
            sys.exit(1)

        config = json.loads(CONFIG_PATH.read_text())
        role = config.get("role", "")
        coordinator_ip = config.get("coordinator_ip", "")
        node_id = config.get("node_id", "")

        if role == "coordinator":
            click.echo("This node is the coordinator. 'pods leave' is for workers only.")
            click.echo("To tear down the pod, stop the gateway process manually.")
            sys.exit(1)

        if not (coordinator_ip and node_id):
            click.echo("Config is malformed — missing coordinator_ip or node_id.")
            sys.exit(1)

        click.echo(f"Leaving pod  coordinator={coordinator_ip}  node_id={node_id}")
        if not yes and not click.confirm("Proceed?"):
            click.echo("Aborted.")
            return

        try:
            r = httpx.post(
                f"http://{coordinator_ip}:8080/internal/leave",
                json={"node_id": node_id},
                headers=internal_headers(),
                timeout=5,
            )
            if r.status_code == 200:
                click.echo("  ✓ coordinator notified")
            else:
                click.echo(f"  ⚠ coordinator returned HTTP {r.status_code} — continuing")
        except Exception as e:
            click.echo(f"  ⚠ coordinator unreachable ({e}) — continuing local cleanup")

        try:
            httpx.post(
                "http://127.0.0.1:8082/internal/shutdown",
                headers=internal_headers(),
                timeout=3,
            )
            click.echo("  ✓ local agent shutdown signaled (stops rpc-server)")
        except Exception as e:
            click.echo(f"  → local agent not running ({e})")

        if not keep_config:
            try:
                CONFIG_PATH.unlink()
                click.echo(f"  ✓ removed {CONFIG_PATH}")
            except FileNotFoundError:
                pass

        click.echo("✓ Left pod.")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
