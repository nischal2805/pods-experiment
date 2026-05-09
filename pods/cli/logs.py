import sys

import click

from ..errors import PodsError
from ..state.store import StateStore


@click.command()
@click.option("--limit", default=50, help="Number of records to show")
@click.option("--key-id", default=None, help="Filter by API key ID prefix")
def cmd(limit: int, key_id: str | None):
    """Show usage logs in reverse chronological order."""
    try:
        store = StateStore()
        state = store.load()
        records = list(reversed(state.usage))
        if key_id:
            records = [r for r in records if r.key_id == key_id]
        records = records[:limit]
        if not records:
            click.echo("No usage records found.")
            return
        for rec in records:
            click.echo(
                f"{rec.timestamp.strftime('%Y-%m-%d %H:%M:%S')}  "
                f"{rec.model:20s}  "
                f"{rec.prompt_tokens:5d}+{rec.completion_tokens:<5d}t  "
                f"{rec.latency_ms:5d}ms  [{rec.backend}]"
            )

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
