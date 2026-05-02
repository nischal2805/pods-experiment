from pathlib import Path

from huggingface_hub import hf_hub_download

from ..errors import InferenceError

MODELS_DIR = Path.home() / "pods" / "models"


def download(name: str, repo: str, filename: str, size_gb: float) -> Path:
    """
    Download GGUF file to ~/pods/models/<filename>.
    Shows real-time progress. Returns path to downloaded file.
    Raises InferenceError on failure.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {name} ({size_gb} GB)...")
    try:
        path = hf_hub_download(
            repo_id=repo,
            filename=filename,
            local_dir=MODELS_DIR,
        )
        return Path(path)
    except Exception as e:
        raise InferenceError(
            f"Failed to download {name}",
            reason=str(e),
            suggestion="Check your internet connection or HuggingFace token",
        )
