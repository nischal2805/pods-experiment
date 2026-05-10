import os
import threading
import time

import uvicorn
from fastapi import Depends, FastAPI

from ..internal_auth import require_internal_access
from ..inference.llamacpp import LlamaCppEngine

app = FastAPI()
_engine: LlamaCppEngine | None = None


@app.post("/internal/start-rpc")
def start_rpc(_: None = Depends(require_internal_access)) -> dict:
    global _engine
    engine = LlamaCppEngine()
    engine.start({"mode": "worker"})
    _engine = engine
    return {"status": "started"}


@app.post("/internal/reconfigure")
def reconfigure(_: None = Depends(require_internal_access)) -> dict:
    global _engine
    if _engine:
        _engine.stop()
    engine = LlamaCppEngine()
    engine.start({"mode": "worker"})
    _engine = engine
    return {"status": "reconfigured"}


@app.post("/internal/stop-rpc")
def stop_rpc(_: None = Depends(require_internal_access)) -> dict:
    global _engine
    if _engine:
        _engine.stop()
        _engine = None
        return {"status": "stopped"}
    return {"status": "not_running"}


@app.post("/internal/shutdown")
def shutdown(_: None = Depends(require_internal_access)) -> dict:
    global _engine
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
