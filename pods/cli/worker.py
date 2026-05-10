import sys
from datetime import datetime, timezone, timedelta

import click
import httpx

from ..errors import PodsError
from ..internal_auth import internal_headers
from ..state.store import StateStore

DEAD_AFTER_S = 600  # 10 minutes


def _dead_workers(state, now: datetime):
    cutoff = now - timedelta(seconds=DEAD_AFTER_S)
    return [m for m in state.members if m.role == "worker" and m.last_seen < cutoff]


@click.group()
def cmd():
    """Worker management."""


@cmd.command("prune")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def prune(yes: bool):
    """Remove workers with last_seen > 10 minutes ago."""
    try:
        store = StateStore()
        state = store.load()
        now = datetime.now(timezone.utc)
        dead = _dead_workers(state, now)
        if not dead:
            click.echo("No dead workers.")
            return

        click.echo(f"Found {len(dead)} dead worker(s):")
        for m in dead:
            age = int((now - m.last_seen).total_seconds())
            click.echo(f"  {m.name:20s}  {m.tailscale_ip:15s}  last_seen {age}s ago")

        if not yes and not click.confirm(f"Remove {len(dead)} dead worker(s)?"):
            click.echo("Aborted.")
            return

        dead_ids = {m.node_id for m in dead}

        def _mutate(s):
            s.members = [m for m in s.members if m.node_id not in dead_ids]
            return len(dead_ids)

        removed = store.update(_mutate)
        click.echo(f"Removed {removed} worker(s).")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@cmd.command("remove")
@click.argument("target")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
def remove(target: str, yes: bool):
    """Remove worker by Tailscale IP or node_id. Best-effort agent shutdown."""
    try:
        store = StateStore()
        state = store.load()
        match = next(
            (m for m in state.members if m.role == "worker" and (m.tailscale_ip == target or m.node_id == target)),
            None,
        )
        if match is None:
            click.echo(f"No worker matches '{target}'.")
            sys.exit(1)
        if match.role == "coordinator":
            click.echo("Refusing to remove coordinator.")
            sys.exit(1)

        click.echo(f"Worker: {match.name}  {match.tailscale_ip}  ({match.node_id})")
        if not yes and not click.confirm("Remove this worker?"):
            click.echo("Aborted.")
            return

        try:
            httpx.post(
                f"http://{match.tailscale_ip}:8082/internal/shutdown",
                headers=internal_headers(),
                timeout=3,
            )
            click.echo("  → agent signaled to shut down")
        except Exception as e:
            click.echo(f"  → agent unreachable ({e}) — removing from state anyway")

        target_ip = match.tailscale_ip
        target_id = match.node_id

        def _mutate(s):
            s.members = [m for m in s.members if m.node_id != target_id]
            for model in s.models:
                model.worker_nodes = [w for w in model.worker_nodes if not w.startswith(f"{target_ip}:")]

        store.update(_mutate)
        click.echo(f"✓ Removed worker {match.name}")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
