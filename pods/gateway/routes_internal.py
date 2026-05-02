import os
import signal
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..models.manager import MODELS_DIR, _start_rpc_on_workers
from ..inference.llamacpp import LlamaCppEngine
from ..state.schema import Member
from ..state.store import StateStore

router = APIRouter()


def get_store() -> StateStore:
    return StateStore()


class RegisterPayload(BaseModel):
    node_id: str
    name: str
    tailscale_ip: str
    role: str
    os: str
    gpu_vram_gb: int = 0


class HeartbeatPayload(BaseModel):
    node_id: str
    connection_type: str = "relay"


class AttachPayload(BaseModel):
    node_id: str
    inference_engine: str
    models: list[str] = []


@router.post("/internal/register")
def register(payload: RegisterPayload, store: StateStore = Depends(get_store)):
    state = store.load()
    now = datetime.now(timezone.utc)
    member = Member(
        node_id=payload.node_id,
        name=payload.name,
        tailscale_ip=payload.tailscale_ip,
        role=payload.role,
        os=payload.os,
        gpu_vram_gb=payload.gpu_vram_gb,
        joined_at=now,
        last_seen=now,
    )
    existing_ids = {m.node_id for m in state.members}
    if payload.node_id not in existing_ids:
        state.members.append(member)
        store.save(state)
    return {"status": "registered", "node_id": member.node_id}


@router.post("/internal/heartbeat")
def heartbeat(payload: HeartbeatPayload, store: StateStore = Depends(get_store)):
    state = store.load()
    for member in state.members:
        if member.node_id == payload.node_id:
            member.last_seen = datetime.now(timezone.utc)
            member.connection_type = payload.connection_type
            store.save(state)
            return {"status": "ok"}
    return {"status": "unknown_node"}


@router.post("/internal/attach")
def attach(payload: AttachPayload, store: StateStore = Depends(get_store)):
    state = store.load()
    for member in state.members:
        if member.node_id == payload.node_id:
            member.inference_engine = payload.inference_engine
            member.models = payload.models
            member.last_seen = datetime.now(timezone.utc)
            store.save(state)
            loaded_model = next((m for m in state.models if m.loaded), None)
            if loaded_model is not None and member.role == "worker":
                threading.Thread(
                    target=_restart_llamacpp,
                    args=(loaded_model.name, loaded_model.loaded_pid, store),
                    daemon=True,
                ).start()
            return {"status": "ok"}
    return {"status": "unknown_node"}


def _restart_llamacpp(model_name: str, old_pid: int, store: StateStore) -> None:
    if old_pid:
        try:
            os.kill(old_pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    state = store.load()
    model = next((m for m in state.models if m.name == model_name), None)
    if model is None:
        return

    rpc_hosts = _start_rpc_on_workers(state)
    engine = LlamaCppEngine()
    config = {
        "mode": "coordinator",
        "model_path": str(MODELS_DIR / model.file),
        "rpc_hosts": rpc_hosts,
    }
    try:
        engine.start(config)
    except Exception:
        return

    fresh = store.load()
    for m in fresh.models:
        if m.name == model_name:
            m.loaded = True
            m.worker_nodes = rpc_hosts
            m.loaded_pid = engine._process.pid if engine._process else 0
            break
    store.save(fresh)


@router.post("/internal/start-rpc")
def start_rpc():
    from ..inference.llamacpp import LlamaCppEngine as _E
    engine = _E()
    engine.start({"mode": "worker"})
    return {"status": "started"}


@router.get("/internal/state")
def get_state(store: StateStore = Depends(get_store)):
    state = store.load()
    return state.model_dump()
