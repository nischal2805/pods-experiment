import sys
import json
from pathlib import Path
from datetime import datetime, timezone

import click
import httpx

from ..errors import PodsError
from ..internal_auth import internal_headers
from ..network.probe import tcp_probe_many
from ..state.store import StateStore
from ..state.schema import PodState, Member

CONFIG_PATH = Path.home() / ".pods" / "config.json"

STALE_AFTER_S = 90
DEAD_AFTER_S = 600  # 10 minutes


def _age(dt: datetime) -> str:
    delta = datetime.now(timezone.utc) - dt
    s = int(delta.total_seconds())
    if s < 60: return f"{s}s ago"
    if s < 3600: return f"{s//60}m ago"
    return f"{s//3600}h ago"


def _label_for(member: Member, probes: dict[tuple[str, int], bool], now: datetime) -> str:
    if member.role != "worker":
        return "OK"
    age = (now - member.last_seen).total_seconds()
    agent_up = probes.get((member.tailscale_ip, 8082), False)
    rpc_up = probes.get((member.tailscale_ip, 50052), False)
    if age > DEAD_AFTER_S:
        return "DEAD"
    if age > STALE_AFTER_S:
        return "STALE"
    if agent_up and rpc_up:
        return "OK"
    return "DEGRADED"


_LABEL_COLORS = {"OK": "green", "DEGRADED": "yellow", "STALE": "yellow", "DEAD": "red"}


def _styled(label: str) -> str:
    color = _LABEL_COLORS.get(label)
    if color and sys.stdout.isatty():
        return click.style(label, fg=color)
    return label


@click.command()
def cmd():
    """Show pod status — members, models, and recent usage."""
    try:
        state: PodState | None = None
        try:
            config = json.loads((CONFIG_PATH).read_text())
            coordinator_ip = config.get("coordinator_ip")
            if coordinator_ip:
                r = httpx.get(
                    f"http://{coordinator_ip}:8080/internal/state",
                    headers=internal_headers(),
                    timeout=5,
                )
                if r.status_code == 200:
                    state = PodState.model_validate(r.json())
        except Exception:
            pass  # will fall back to local state.json below

        if state is None:
            store = StateStore()
            state = store.load()

        assert state is not None

        worker_targets: list[tuple[str, int]] = []
        for m in state.members:
            if m.role == "worker":
                worker_targets.append((m.tailscale_ip, 8082))
                worker_targets.append((m.tailscale_ip, 50052))
        probes = tcp_probe_many(worker_targets, timeout=1.0) if worker_targets else {}

        click.echo(f"\nPod: {state.pod.name}  ({state.pod.id[:8]}...)")
        click.echo(f"Coordinator: {state.pod.coordinator_ip}")
        click.echo(f"Engine: {state.pod.inference_engine}")

        now = datetime.now(timezone.utc)
        click.echo(f"\nMembers ({len(state.members)}):")
        for m in state.members:
            label = _label_for(m, probes, now)
            age = _age(m.last_seen)
            click.echo(
                f"  {m.name:20s}  {m.role:12s}  {m.tailscale_ip:15s}  "
                f"{m.connection_type:6s}  {age:12s}  {_styled(label)}"
            )

        click.echo(f"\nModels ({len(state.models)}):")
        for m in state.models:
            status_str = "loaded" if m.loaded else "available"
            click.echo(f"  {m.name:20s}  {m.size_gb:.1f}GB  {status_str}")
        if not state.models:
            click.echo("  (none — run 'pods model add <name>')")

        click.echo(f"\nAPI Keys ({len(state.keys)}):")
        for k in state.keys:
            click.echo(f"  {k.label:20s}  {k.total_requests} requests  {k.total_tokens} tokens")

        if state.usage:
            click.echo(f"\nRecent usage (last 5):")
            for rec in reversed(state.usage[-5:]):
                click.echo(f"  {rec.model:20s}  {rec.prompt_tokens}+{rec.completion_tokens}t  {rec.latency_ms}ms  [{rec.backend}]")

    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
