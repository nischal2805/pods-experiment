import sys

import click

from ..errors import PodsError
from ..state.defaults import new_key
from ..state.store import StateStore


@click.command()
@click.argument("label")
def cmd(label: str):
    """Generate a new API key with the given label."""
    try:
        store = StateStore()
        state = store.load()
        key = new_key(label)
        state.keys.append(key)
        store.save(state)
        click.echo(f"Key generated:")
        click.echo(f"  {key.key}")
        click.echo(f"\nLabel: {label}")
        click.echo("Store this key now — it will not be shown again.")

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
