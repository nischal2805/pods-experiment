REGISTRY = {
    "qwen0.5b": {
        "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "filename": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_gb": 0.4,
    },
    "qwen1.5b": {
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_gb": 1.0,
    },
    "qwen7b": {
        "repo": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
        "shards": [
            "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
            "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
        ],
        "size_gb": 5.0,
    },
    "qwen32b": {
        "repo": "Qwen/Qwen2.5-32B-Instruct-GGUF",
        "filename": "qwen2.5-32b-instruct-q4_k_m-00001-of-00005.gguf",
        "shards": [
            "qwen2.5-32b-instruct-q4_k_m-00001-of-00005.gguf",
            "qwen2.5-32b-instruct-q4_k_m-00002-of-00005.gguf",
            "qwen2.5-32b-instruct-q4_k_m-00003-of-00005.gguf",
            "qwen2.5-32b-instruct-q4_k_m-00004-of-00005.gguf",
            "qwen2.5-32b-instruct-q4_k_m-00005-of-00005.gguf",
        ],
        "size_gb": 20.0,
    },
    "phi3.5mini": {
        "repo": "bartowski/Phi-3.5-mini-instruct-GGUF",
        "filename": "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "size_gb": 2.4,
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
