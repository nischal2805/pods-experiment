import shutil
import subprocess
from pathlib import Path

import httpx

from .base import EngineStatus, HealthStatus, InferenceEngine

LOGS_DIR = Path.home() / ".pods" / "logs"
HEALTH_URL = "http://localhost:52415/v1/models"


class ExoEngine(InferenceEngine):
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None

    def detect(self) -> bool:
        return shutil.which("exo") is not None

    def start(self, config: dict) -> None:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log = open(LOGS_DIR / "exo.log", "a")
        self._process = subprocess.Popen(["exo"], stdout=log, stderr=log)

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
                return [m["id"] for m in r.json().get("data", [])]
        except Exception:
            pass
        return []
