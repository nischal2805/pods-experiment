import sys
import json
from pathlib import Path

import click

from ..errors import PodsError
from ..network.invite import encode_invite
from ..network.tailscale import get_ip
from ..state.store import StateStore

CONFIG_PATH = Path.home() / ".pods" / "config.json"


@click.command()
def cmd():
    """Generate an invite link for a new node to join this pod."""
    try:
        store = StateStore()
        state = store.load()
        tailscale_ip = get_ip()
        config = json.loads(CONFIG_PATH.read_text())
        internal_token = config.get("internal_token")
        if not internal_token:
            raise PodsError(
                "Internal token is missing",
                reason=f"{CONFIG_PATH} has no internal_token",
                suggestion="Run 'pods init <name>' again on the coordinator",
            )

        link = encode_invite(tailscale_ip, state.pod.name, internal_token)
        click.echo("Invite link (share this with the joining machine):")
        click.echo(f"\n  pods join {link} --authkey <tailscale-key>\n")
        click.echo(
            "⚠ This link contains a sensitive auth token and expires in 24 hours.\n"
            "  Share it only over secure channels — do not paste it in public forums or logs.",
            err=True,
        )

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
