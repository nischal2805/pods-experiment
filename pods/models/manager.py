from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

from ..errors import InferenceError
from ..inference.llamacpp import LlamaCppEngine
from ..state.schema import Model, PodState
from ..state.store import StateStore
from .downloader import download
from .registry import resolve

MODELS_DIR = Path.home() / "pods" / "models"


def _online_workers(state: PodState) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
    return [m for m in state.members if m.role == "worker" and m.last_seen > cutoff]


def _start_rpc_on_workers(state: PodState) -> list[str]:
    workers = _online_workers(state)
    if not workers:
        return []
    rpc_hosts = []
    for w in workers:
        try:
            r = httpx.post(f"http://{w.tailscale_ip}:8082/internal/start-rpc", timeout=10)
            if r.status_code == 200:
                rpc_hosts.append(f"{w.tailscale_ip}:50052")
                print(f"  [pods] Started rpc-server on {w.name} ({w.tailscale_ip})")
            else:
                print(f"  [pods] Worker {w.name} returned {r.status_code} — skipping")
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
                suggestion="Available: qwen32b, qwen7b, gemma9b, llama8b",
            )
        path = download(name, entry["repo"], entry["filename"], entry["size_gb"])
        return self.register(name, path.name, size_gb=entry["size_gb"])

    def register(self, name: str, filename: str, size_gb: float = 0.0) -> Model:
        model_path = MODELS_DIR / filename
        if not model_path.exists():
            raise InferenceError(
                f"Model file not found: {filename}",
                reason=f"{model_path} does not exist",
                suggestion="Run 'pods model add <name>' to download the model first",
            )
        state = self.store.load()
        model = Model(name=name, file=filename, size_gb=size_gb)
        state.models = [m for m in state.models if m.name != name]
        state.models.append(model)
        self.store.save(state)
        return model

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
        model.loaded = True
        model.worker_nodes = rpc_hosts
        model.loaded_pid = engine._process.pid if engine._process else 0
        self.store.save(state)
        print(f"[pods] Model '{name}' ready.")

    def list_models(self) -> list[Model]:
        return self.store.load().models
