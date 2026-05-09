from pathlib import Path

from huggingface_hub import hf_hub_download

from ..errors import InferenceError

MODELS_DIR = Path.home() / "pods" / "models"


def download(name: str, repo: str, filename: str, size_gb: float, shards: list[str] | None = None) -> Path:
    """Download GGUF file(s) to ~/pods/models/. Returns path to first/only file."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    files_to_fetch = shards if shards else [filename]
    print(f"Downloading {name} ({size_gb} GB, {len(files_to_fetch)} file(s))...")
    try:
        for i, shard in enumerate(files_to_fetch, 1):
            if len(files_to_fetch) > 1:
                print(f"  [{i}/{len(files_to_fetch)}] {shard}")
            hf_hub_download(repo_id=repo, filename=shard, local_dir=MODELS_DIR)
        return MODELS_DIR / filename
    except Exception as e:
        raise InferenceError(
            f"Failed to download {name}",
            reason=str(e),
            suggestion="Check your internet connection or set HF_TOKEN for gated models",
        )
