import sys

import click

from ..errors import PodsError
from ..network.invite import encode_invite
from ..network.tailscale import get_ip
from ..state.store import StateStore


@click.command()
@click.option("--authkey", required=True, help="Tailscale pre-auth key from admin.tailscale.com")
def cmd(authkey: str):
    """Generate an invite link for a new node to join this pod."""
    try:
        store = StateStore()
        state = store.load()
        tailscale_ip = get_ip()

        link = encode_invite(tailscale_ip, authkey, state.pod.name)
        click.echo(f"Invite link (share this with the joining machine):")
        click.echo(f"\n  pods join {link}\n")
        click.echo("This link contains a Tailscale auth key. Keep it private.")

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
