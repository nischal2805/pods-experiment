import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from ..errors import InferenceError
from ..internal_auth import internal_headers
from ..inference.llamacpp import LlamaCppEngine
from ..network.probe import tcp_probe
from ..state.schema import Model, PodState
from ..state.store import StateStore
from .downloader import download
from .registry import resolve

_RPC_HOST_RE = re.compile(r"^[0-9a-fA-F:.]+:\d{1,5}$")


def _validate_rpc_hosts(rpc_hosts: list[str]) -> list[str]:
    bad = [h for h in rpc_hosts if not _RPC_HOST_RE.match(h)]
    if bad:
        raise InferenceError(
            f"Invalid RPC host format: {bad[0]}",
            reason="RPC hosts must be IP:PORT",
            suggestion="Pass --rpc 100.0.0.2:50052 (Tailscale IPs only)",
        )
    return rpc_hosts

RPC_PORT = 50052
RPC_PROBE_TIMEOUT_S = 3.0
RPC_PROBE_DEADLINE_S = 5.0
RPC_PROBE_INTERVAL_S = 1.0

MODELS_DIR = Path.home() / "pods" / "models"


ONLINE_CUTOFF_SECONDS = 90  # 3x heartbeat interval (30s)


def _online_workers(state: PodState) -> list:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=ONLINE_CUTOFF_SECONDS)
    online = []
    for m in state.members:
        if m.role != "worker":
            continue
        if m.last_seen > cutoff:
            online.append(m)
        else:
            age = int((now - m.last_seen).total_seconds())
            print(f"[pods] Skipping worker {m.name} ({m.tailscale_ip}) — last_seen {age}s ago")
    return online


def _wait_rpc_reachable(host: str, port: int = RPC_PORT) -> bool:
    deadline = time.monotonic() + RPC_PROBE_DEADLINE_S
    while time.monotonic() < deadline:
        if tcp_probe(host, port, timeout=RPC_PROBE_TIMEOUT_S):
            return True
        time.sleep(RPC_PROBE_INTERVAL_S)
    return False


def _start_rpc_on_workers(state: PodState) -> list[str]:
    workers = _online_workers(state)
    if not workers:
        return []
    rpc_hosts = []
    for w in workers:
        try:
            r = httpx.post(
                f"http://{w.tailscale_ip}:8082/internal/start-rpc",
                headers=internal_headers(),
                timeout=10,
            )
            if r.status_code != 200:
                print(f"  [pods] Worker {w.name} returned {r.status_code} — skipping")
                continue
            print(f"  [pods] Started rpc-server on {w.name} ({w.tailscale_ip}) — probing :{RPC_PORT}")
            if not _wait_rpc_reachable(w.tailscale_ip):
                print(
                    f"  [pods] Worker {w.name} rpc-server unreachable on "
                    f"{w.tailscale_ip}:{RPC_PORT} after {RPC_PROBE_DEADLINE_S:.0f}s — skipping"
                )
                continue
            rpc_hosts.append(f"{w.tailscale_ip}:{RPC_PORT}")
        except Exception as e:
            print(f"  [pods] Could not reach worker {w.name} ({w.tailscale_ip}): {e}")
    return rpc_hosts


class ModelManager:
    def __init__(self, store: StateStore | None = None):
        self.store = store or StateStore()

    def add(self, name: str) -> Model:
        try:
            entry = resolve(name)
        except KeyError:
            raise InferenceError(
                f"Unknown model '{name}'",
                reason=f"'{name}' is not in the built-in registry",
                suggestion="Run 'pods model list' to see available models",
            )
        path = download(name, entry["repo"], entry["filename"], entry["size_gb"], shards=entry.get("shards"))
        return self.register(name, path.name, size_gb=entry["size_gb"])

    def register(self, name: str, filename: str, size_gb: float = 0.0) -> Model:
        raw_path = MODELS_DIR / filename
        if raw_path.is_symlink():
            raise InferenceError(
                f"Refusing to register symlink: {filename}",
                reason=f"{raw_path} is a symlink",
                suggestion="Place the GGUF file directly in ~/pods/models/",
            )
        model_path = raw_path.resolve()
        if not model_path.is_relative_to(MODELS_DIR.resolve()):
            raise InferenceError(
                f"Invalid filename: {filename}",
                reason="Filename must not escape the models directory",
                suggestion="Use a plain filename without path separators",
            )
        if not model_path.exists():
            raise InferenceError(
                f"Model file not found: {filename}",
                reason=f"{model_path} does not exist",
                suggestion="Run 'pods model add <name>' to download the model first",
            )
        def _mutate(state: PodState) -> Model:
            model = Model(name=name, file=filename, size_gb=size_gb)
            state.models = [m for m in state.models if m.name != name]
            state.models.append(model)
            return model

        return self.store.update(_mutate)

    def load(self, name: str, rpc_hosts: list[str] | None = None) -> None:
        state = self.store.load()
        model = next((m for m in state.models if m.name == name), None)
        if model is None:
            raise InferenceError(
                f"Model '{name}' is not registered",
                reason="Model not found in state.json",
                suggestion=f"Run 'pods model add {name}' to download and register it",
            )
        engine = LlamaCppEngine()
        if not engine.detect():
            raise InferenceError(
                "llama.cpp binaries not found",
                reason="llama-server or rpc-server binary is missing",
                suggestion="Ensure binaries are at ~/pods/llama.cpp/build/bin/",
            )
        if rpc_hosts is None:
            print("[pods] Discovering online workers...")
            rpc_hosts = _start_rpc_on_workers(state)
        else:
            rpc_hosts = _validate_rpc_hosts(rpc_hosts)
        if rpc_hosts:
            print(f"[pods] Loading with {len(rpc_hosts)} RPC worker(s): {', '.join(rpc_hosts)}")
        else:
            print("[pods] No online workers found — loading on coordinator GPU only")
        config = {
            "mode": "coordinator",
            "model_path": str(MODELS_DIR / model.file),
            "rpc_hosts": rpc_hosts,
        }
        engine.start(config)
        loaded_pid = engine._process.pid if engine._process else 0
        self.store.update(lambda s: _mark_model_loaded(s, name, rpc_hosts, loaded_pid))
        print(f"[pods] Model '{name}' ready.")

    def list_models(self) -> list[Model]:
        return self.store.load().models

    def unload(self, name: str) -> dict:
        import os
        import signal

        state = self.store.load()
        model = next((m for m in state.models if m.name == name), None)
        if model is None:
            raise InferenceError(
                f"Model '{name}' is not registered",
                reason="Model not found in state.json",
                suggestion="Run 'pods model list' to see registered models",
            )
        if not model.loaded:
            raise InferenceError(
                f"Model '{name}' is not loaded",
                reason="loaded=False in state.json",
                suggestion="Nothing to unload",
            )

        result = {"killed_pid": False, "workers_stopped": [], "workers_failed": []}

        if model.loaded_pid:
            try:
                os.kill(model.loaded_pid, signal.SIGTERM)
                result["killed_pid"] = True
            except (ProcessLookupError, OSError):
                pass

        for rpc_host in model.worker_nodes:
            host = rpc_host.split(":", 1)[0]
            try:
                r = httpx.post(
                    f"http://{host}:8082/internal/stop-rpc",
                    headers=internal_headers(),
                    timeout=5,
                )
                if r.status_code == 200:
                    result["workers_stopped"].append(host)
                else:
                    result["workers_failed"].append(f"{host} (HTTP {r.status_code})")
            except Exception as exc:
                result["workers_failed"].append(f"{host} ({exc})")

        def _mutate(s):
            for m in s.models:
                if m.name == name:
                    m.loaded = False
                    m.reloading = False
                    m.loaded_pid = 0
                    m.worker_nodes = []
                    return

        self.store.update(_mutate)
        return result


def _mark_model_loaded(state: PodState, name: str, rpc_hosts: list[str], loaded_pid: int) -> None:
    for model in state.models:
        if model.name == name:
            model.loaded = True
            model.worker_nodes = rpc_hosts
            model.loaded_pid = loaded_pid
            return
