import sys
import json
from pathlib import Path

import click
import httpx

from ..errors import PodsError
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

        engine_name, engine = FallbackOrchestrator().start_best_engine({})
        click.echo(f"✓ Active engine: {engine_name}")

        models = engine.get_models()

        if coordinator_ip and node_id:
            try:
                httpx.post(
                    f"http://{coordinator_ip}:8080/internal/attach",
                    json={"node_id": node_id, "inference_engine": engine_name, "models": models},
                    timeout=5,
                )
            except Exception:
                pass  # Coordinator unreachable — continue anyway

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
