import uvicorn
from fastapi import FastAPI

from ..inference.llamacpp import LlamaCppEngine

app = FastAPI()
_engine: LlamaCppEngine | None = None


@app.post("/internal/start-rpc")
def start_rpc() -> dict:
    global _engine
    engine = LlamaCppEngine()
    engine.start({"mode": "worker"})
    _engine = engine
    return {"status": "started"}


@app.post("/internal/reconfigure")
def reconfigure() -> dict:
    global _engine
    if _engine:
        _engine.stop()
    engine = LlamaCppEngine()
    engine.start({"mode": "worker"})
    _engine = engine
    return {"status": "reconfigured"}


@app.get("/internal/health")
def health() -> dict:
    return {"status": "ok"}


def run(host: str = "0.0.0.0", port: int = 8082) -> None:
    uvicorn.run(app, host=host, port=port, log_level="warning")
