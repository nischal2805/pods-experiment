import httpx

from ..errors import InferenceError

BACKENDS = {
    "llamacpp": "http://localhost:8081",
    "exo": "http://localhost:52415",
    "ollama": "http://localhost:11434",
}


def select_backend(model: str, state) -> tuple[str, str]:
    """
    Given a model name and PodState, find the best available backend.

    Returns (backend_name, base_url) for the first backend that:
    1. Has the model loaded (in state.models[].loaded) OR is Ollama (can serve any model)
    2. Is actually reachable (health check passes)

    Raises InferenceError if no backend can serve the model.
    """
    tried = {}

    loaded_model = next((m for m in state.models if m.name == model and m.loaded), None)

    for backend_name, url in BACKENDS.items():
        if backend_name == "ollama":
            if _is_reachable(url):
                return (backend_name, url)
            tried[backend_name] = "connection refused — Ollama not running"
        elif loaded_model is not None:
            if _is_reachable(url):
                return (backend_name, url)
            tried[backend_name] = f"connection refused — {backend_name} not running"
        else:
            tried[backend_name] = f"model {model} not loaded"

    raise InferenceError(
        f"All backends failed for model {model}",
        reason=str(tried),
        suggestion="Run 'pods status' to check which nodes are online. Run 'pods model load <name>' if model not loaded.",
    )


def _is_reachable(url: str) -> bool:
    """Return True if the backend health endpoint responds 200."""
    try:
        r = httpx.get(f"{url}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False
