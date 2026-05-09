import sys

import click

from ..errors import PodsError
from ..network.tailscale import ping
from ..state.store import StateStore


@click.command()
def cmd():
    """Ping all pod members and report connection type (direct/relay)."""
    try:
        store = StateStore()
        state = store.load()
        members = [m for m in state.members if m.role == "worker"]
        if not members:
            click.echo("No worker nodes found.")
            return

        relayed = []
        for m in members:
            result = ping(m.tailscale_ip)
            status = "direct" if result["direct"] else "relay"
            click.echo(f"  {m.name:20s}  {m.tailscale_ip:15s}  {status}")
            if not result["direct"]:
                relayed.append(m.tailscale_ip)

        if relayed:
            click.echo(f"\n{len(relayed)} peer(s) using relay. Run 'pods ping' a few more times to help Tailscale establish direct paths.")

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
