import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI

from ..internal_auth import require_internal_access
from ..inference.llamacpp import LlamaCppEngine
from ..agent.heartbeat import HeartbeatThread, _send_heartbeat_once

_engine: LlamaCppEngine | None = None
_engine_lock = threading.Lock()  # guards _engine across concurrent start/stop/reconfigure calls
_heartbeat: HeartbeatThread | None = None

_CONFIG_PATH = Path.home() / ".pods" / "config.json"


@asynccontextmanager
async def _lifespan(_application: FastAPI):
    global _heartbeat
    try:
        cfg = json.loads(_CONFIG_PATH.read_text())
        coordinator_ip = cfg["coordinator_ip"]
        node_id = cfg["node_id"]
        coordinator_url = f"http://{coordinator_ip}:8080"
        try:
            _send_heartbeat_once(coordinator_url, node_id)
        except Exception:
            pass
        _heartbeat = HeartbeatThread(coordinator_url, node_id, interval=30)
        _heartbeat.start()
    except Exception:
        pass  # no config — agent started outside pods join
    yield
    if _heartbeat:
        _heartbeat.stop()


app = FastAPI(lifespan=_lifespan)


@app.post("/internal/start-rpc")
def start_rpc(_: None = Depends(require_internal_access)) -> dict:
    global _engine
    with _engine_lock:
        # Stop any existing rpc-server before starting a new one to prevent zombie processes
        # fighting over port 50052.
        if _engine is not None:
            try:
                _engine.stop()
            except Exception:
                pass
            _engine = None
        engine = LlamaCppEngine()
        engine.start({"mode": "worker"})
        _engine = engine
    return {"status": "started"}


@app.post("/internal/reconfigure")
def reconfigure(_: None = Depends(require_internal_access)) -> dict:
    global _engine
    with _engine_lock:
        if _engine:
            _engine.stop()
        engine = LlamaCppEngine()
        engine.start({"mode": "worker"})
        _engine = engine
    return {"status": "reconfigured"}


@app.post("/internal/stop-rpc")
def stop_rpc(_: None = Depends(require_internal_access)) -> dict:
    global _engine
    with _engine_lock:
        if _engine:
            _engine.stop()
            _engine = None
            return {"status": "stopped"}
    return {"status": "not_running"}


@app.post("/internal/shutdown")
def shutdown(_: None = Depends(require_internal_access)) -> dict:
    global _engine
    with _engine_lock:
        if _engine:
            try:
                _engine.stop()
            except Exception:
                pass
            _engine = None

    def _exit_after_response() -> None:
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=_exit_after_response, daemon=True).start()
    return {"status": "shutting_down"}


@app.get("/internal/health")
def health(_: None = Depends(require_internal_access)) -> dict:
    return {"status": "ok"}


def run(host: str = "0.0.0.0", port: int = 8082) -> None:
    uvicorn.run(app, host=host, port=port, log_level="warning")
