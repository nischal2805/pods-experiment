REGISTRY = {
    "qwen32b": {
        "repo": "Qwen/Qwen2.5-32B-Instruct-GGUF",
        "filename": "qwen2.5-32b-instruct-q4_k_m.gguf",
        "size_gb": 20.0,
    },
    "qwen7b": {
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "size_gb": 5.0,
    },
    "gemma9b": {
        "repo": "google/gemma-2-9b-it-GGUF",
        "filename": "gemma-2-9b-it-Q4_K_M.gguf",
        "size_gb": 6.0,
    },
    "llama8b": {
        "repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "size_gb": 5.0,
    },
}


def resolve(name: str) -> dict:
    """Return registry entry for name. Raises KeyError if not found."""
    return REGISTRY[name]


def list_names() -> list[str]:
    """Return sorted list of registered model names."""
    return sorted(REGISTRY.keys())
