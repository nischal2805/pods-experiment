import subprocess
import time
from pathlib import Path

import httpx

from ..errors import InferenceError
from ..platform.setup import LLAMA_SERVER, RPC_SERVER
from .base import EngineStatus, HealthStatus, InferenceEngine

LOGS_DIR = Path.home() / ".pods" / "logs"
HEALTH_URL = "http://localhost:8081/health"
HEALTH_TIMEOUT = 120


class LlamaCppEngine(InferenceEngine):
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._mode: str = ""  # "coordinator" | "worker"

    def detect(self) -> bool:
        return LLAMA_SERVER.exists() and RPC_SERVER.exists()

    def start(self, config: dict) -> None:
        mode = config.get("mode", "worker")
        self._mode = mode
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        if mode == "worker":
            self._start_rpc_server()
        else:
            self._start_llama_server(config)

    def _start_rpc_server(self) -> None:
        log = open(LOGS_DIR / "rpc-server.log", "a")
        self._process = subprocess.Popen(
            [str(RPC_SERVER), "--host", "0.0.0.0", "--port", "50052"],
            stdout=log,
            stderr=log,
        )

    def _start_llama_server(self, config: dict) -> None:
        model_path = config["model_path"]
        rpc_hosts: list[str] = config.get("rpc_hosts", [])
        cmd = [
            str(LLAMA_SERVER),
            "--model", model_path,
            "--host", "127.0.0.1",
            "--port", "8081",
            "-ngl", "99",
        ]
        if rpc_hosts:
            cmd += ["--rpc", ",".join(rpc_hosts)]
        log = open(LOGS_DIR / "llama-server.log", "a")
        self._process = subprocess.Popen(cmd, stdout=log, stderr=log)
        self._wait_for_health()

    def _wait_for_health(self) -> None:
        deadline = time.time() + HEALTH_TIMEOUT
        while time.time() < deadline:
            try:
                r = httpx.get(HEALTH_URL, timeout=2)
                if r.status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(2)
        raise InferenceError(
            "llama-server failed to become healthy",
            reason=f"Health check timed out after {HEALTH_TIMEOUT}s",
            suggestion="Check ~/.pods/logs/llama-server.log for errors",
        )

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def health(self) -> HealthStatus:
        if self._mode == "worker":
            if self._process and self._process.poll() is None:
                return HealthStatus(EngineStatus.RUNNING)
            return HealthStatus(EngineStatus.STOPPED)
        try:
            r = httpx.get(HEALTH_URL, timeout=2)
            if r.status_code == 200:
                return HealthStatus(EngineStatus.RUNNING)
        except Exception:
            pass
        return HealthStatus(EngineStatus.STOPPED)

    def get_models(self) -> list[str]:
        try:
            r = httpx.get("http://localhost:8081/v1/models", timeout=2)
            if r.status_code == 200:
                return [m["id"] for m in r.json().get("data", [])]
        except Exception:
            pass
        return []
