import sys
import json
from pathlib import Path

import click
import httpx

from ..errors import PodsError
from ..internal_auth import internal_headers
from ..inference.fallback import FallbackOrchestrator

CONFIG_PATH = Path.home() / ".pods" / "config.json"


@click.command()
def cmd():
    """Detect and start the best available inference backend on this node."""
    try:
        try:
            config = json.loads(CONFIG_PATH.read_text())
        except Exception:
            click.echo("Not joined to a pod. Run 'pods join <link>' first.", err=True)
            sys.exit(1)

        coordinator_ip = config.get("coordinator_ip")
        node_id = config.get("node_id")
        role = config.get("role", "worker")

        if role == "coordinator":
            click.echo("Coordinator node: inference is started via 'pods model load', not attach.")
            click.echo("Run 'pods model load <name>' to start inference.")
            return

        engine_name, engine = FallbackOrchestrator().start_best_engine({"mode": "worker"})
        click.echo(f"✓ Active engine: {engine_name}")

        models = engine.get_models()

        if coordinator_ip and node_id:
            try:
                r = httpx.post(
                    f"http://{coordinator_ip}:8080/internal/attach",
                    json={"node_id": node_id, "inference_engine": engine_name, "models": models},
                    headers=internal_headers(),
                    timeout=5,
                )
                r.raise_for_status()
            except Exception as e:
                click.echo(f"  ⚠ Could not notify coordinator ({e}) — inference still active locally", err=True)

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
