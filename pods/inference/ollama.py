import shutil
import subprocess
from pathlib import Path

import httpx

from ..errors import InferenceError
from .base import EngineStatus, HealthStatus, InferenceEngine

LOGS_DIR = Path.home() / ".pods" / "logs"
HEALTH_URL = "http://localhost:11434/api/tags"


class OllamaEngine(InferenceEngine):
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None

    def detect(self) -> bool:
        return shutil.which("ollama") is not None

    def start(self, config: dict) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOGS_DIR / "ollama.log", "a") as log:
            self._process = subprocess.Popen(["ollama", "serve"], stdout=log, stderr=log)

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def health(self) -> HealthStatus:
        try:
            r = httpx.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                return HealthStatus(EngineStatus.RUNNING)
        except Exception:
            pass
        return HealthStatus(EngineStatus.STOPPED)

    def get_models(self) -> list[str]:
        try:
            r = httpx.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                return [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            pass
        return []

    def pull_model(self, model_name: str) -> None:
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise InferenceError(
                f"Failed to pull model {model_name}",
                reason=result.stderr.strip(),
                suggestion="Check that ollama is running and the model name is correct",
            )
