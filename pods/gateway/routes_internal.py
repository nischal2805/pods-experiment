from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

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
            store.save(state)
            return {"status": "ok"}
    return {"status": "unknown_node"}


@router.post("/internal/start-rpc")
def start_rpc():
    from ..inference.llamacpp import LlamaCppEngine
    engine = LlamaCppEngine()
    engine.start({"mode": "worker"})
    return {"status": "started"}


@router.get("/internal/state")
def get_state(store: StateStore = Depends(get_store)):
    state = store.load()
    return state.model_dump()
