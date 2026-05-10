import sys

import click

from ..errors import PodsError
from ..models.manager import ModelManager


@click.group()
def cmd():
    """Manage models — add, load, list, register."""


@cmd.command("add")
@click.argument("name")
def add(name: str):
    """Download a model by name and register it."""
    try:
        mgr = ModelManager()
        model = mgr.add(name)
        click.echo(f"✓ Added {model.name} ({model.size_gb:.1f}GB) → {model.file}")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@cmd.command("load")
@click.argument("name")
@click.option("--rpc", "rpc_hosts", multiple=True, help="Explicit RPC worker addresses (skips auto-discovery)")
def load(name: str, rpc_hosts: tuple):
    """Load a model into memory and start inference."""
    try:
        mgr = ModelManager()
        mgr.load(name, list(rpc_hosts) if rpc_hosts else None)
        click.echo(f"✓ Model '{name}' loaded.")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@cmd.command("list")
def list_models():
    """List all registered models."""
    try:
        mgr = ModelManager()
        models = mgr.list_models()
        if not models:
            click.echo("No models registered. Run 'pods model add <name>'.")
            return
        for m in models:
            status = "● loaded" if m.loaded else "○ available"
            click.echo(f"  {m.name:20s}  {m.size_gb:5.1f}GB  {status}  {m.file}")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@cmd.command("register")
@click.argument("name")
@click.argument("filename")
def register(name: str, filename: str):
    """Register a GGUF file already in ~/pods/models/ without downloading."""
    try:
        mgr = ModelManager()
        model = mgr.register(name, filename)
        click.echo(f"✓ Registered {model.name} ({model.size_gb:.1f}GB)")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@cmd.command("unload")
@click.argument("name")
def unload(name: str):
    """Unload a model — kill llama-server and stop rpc-server on workers."""
    try:
        mgr = ModelManager()
        result = mgr.unload(name)
        if result["killed_pid"]:
            click.echo("  ✓ llama-server terminated")
        else:
            click.echo("  → llama-server pid not running (already gone)")
        for host in result["workers_stopped"]:
            click.echo(f"  ✓ stopped rpc-server on {host}")
        for host in result["workers_failed"]:
            click.echo(f"  ⚠ failed on {host}")
        click.echo(f"✓ Model '{name}' unloaded.")
    except PodsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
