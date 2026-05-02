from pathlib import Path

from ..errors import InferenceError
from ..inference.llamacpp import LlamaCppEngine
from ..state.schema import Model
from ..state.store import StateStore
from .downloader import download
from .registry import resolve

MODELS_DIR = Path.home() / "pods" / "models"


class ModelManager:
    def __init__(self, store: StateStore | None = None):
        self.store = store or StateStore()

    def add(self, name: str) -> Model:
        """
        Download model by friendly name. Register in state.json.
        Returns the Model object. Raises InferenceError if name unknown.
        """
        try:
            entry = resolve(name)
        except KeyError:
            raise InferenceError(
                f"Unknown model '{name}'",
                reason=f"'{name}' is not in the built-in registry",
                suggestion="Run 'pods models list' to see available models",
            )
        path = download(name, entry["repo"], entry["filename"], entry["size_gb"])
        return self.register(name, path.name, size_gb=entry["size_gb"])

    def register(self, name: str, filename: str, size_gb: float = 0.0) -> Model:
        """
        Register a model already present in ~/pods/models/ without downloading.
        Raises InferenceError if file not found.
        """
        model_path = MODELS_DIR / filename
        if not model_path.exists():
            raise InferenceError(
                f"Model file not found: {filename}",
                reason=f"{model_path} does not exist",
                suggestion="Run 'pods models add <name>' to download the model first",
            )
        state = self.store.load()
        model = Model(name=name, file=filename, size_gb=size_gb)
        state.models = [m for m in state.models if m.name != name]
        state.models.append(model)
        self.store.save(state)
        return model

    def load(self, name: str, rpc_hosts: list[str] | None = None) -> None:
        """
        Start llama-server with the named model and optional RPC workers.
        Updates state.json to mark model as loaded.
        Raises InferenceError if model not registered or binaries missing.
        """
        state = self.store.load()
        model = next((m for m in state.models if m.name == name), None)
        if model is None:
            raise InferenceError(
                f"Model '{name}' is not registered",
                reason="Model not found in state.json",
                suggestion=f"Run 'pods models add {name}' to download and register it",
            )
        engine = LlamaCppEngine()
        if not engine.detect():
            raise InferenceError(
                "llama.cpp binaries not found",
                reason="llama-server or rpc-server binary is missing",
                suggestion="Run 'pods setup' to install llama.cpp",
            )
        config = {
            "mode": "coordinator",
            "model_path": str(MODELS_DIR / model.file),
            "rpc_hosts": rpc_hosts or [],
        }
        engine.start(config)
        model.loaded = True
        model.worker_nodes = rpc_hosts or []
        self.store.save(state)

    def list_models(self) -> list[Model]:
        """Return models from state.json."""
        return self.store.load().models
