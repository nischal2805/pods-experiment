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


@app.get("/internal/health")
def health(_: None = Depends(require_internal_access)) -> dict:
    return {"status": "ok"}


def run(host: str = "0.0.0.0", port: int = 8082) -> None:
    uvicorn.run(app, host=host, port=port, log_level="warning")
