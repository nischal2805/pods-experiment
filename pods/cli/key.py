import sys

import click

from ..errors import PodsError
from ..state.defaults import key_id_from_token
from ..state.store import StateStore


@click.group()
def cmd():
    """API key management."""


@cmd.command("list")
def list_keys():
    """List API keys (label, requests, tokens)."""
    try:
        store = StateStore()
        state = store.load()
        if not state.keys:
            click.echo("No API keys. Run 'pods keygen <label>'.")
            return
        for k in state.keys:
            click.echo(
                f"  {k.label:20s}  {k.key_id:14s}  "
                f"{k.total_requests} requests  {k.total_tokens} tokens"
            )
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@cmd.command("revoke")
@click.argument("target")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def revoke(target: str, yes: bool):
    """Revoke API key by label or full pk_ token."""
    try:
        store = StateStore()
        state = store.load()

        candidate_id = key_id_from_token(target) if target.startswith("pk_") else None
        matches = [
            k for k in state.keys
            if k.label == target or (candidate_id and k.key_id == candidate_id)
        ]
        if not matches:
            click.echo(f"No key matches '{target}'.")
            sys.exit(1)
        if len(matches) > 1:
            click.echo(f"Ambiguous — {len(matches)} keys match label '{target}':")
            for k in matches:
                click.echo(f"  {k.label}  {k.key_id}")
            click.echo("Pass the full pk_ token to disambiguate.")
            sys.exit(1)

        match = matches[0]
        click.echo(f"Key: {match.label}  ({match.key_id})  "
                   f"{match.total_requests} requests")
        if not yes and not click.confirm("Revoke this key?"):
            click.echo("Aborted.")
            return

        match_id = match.key_id

        def _mutate(s):
            s.keys = [k for k in s.keys if k.key_id != match_id]

        store.update(_mutate)
        click.echo(f"✓ Revoked '{match.label}'")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
