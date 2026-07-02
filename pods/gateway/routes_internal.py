import logging
import os
import signal
import threading
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..internal_auth import require_internal_access
from ..models.manager import MODELS_DIR, _start_rpc_on_workers
from ..inference.llamacpp import LlamaCppEngine
from ..state.schema import Member
from ..state.store import StateStore

_log = logging.getLogger("pods.gateway")

DEAD_SWEEP_AFTER_S = 600  # 10 minutes


router = APIRouter(dependencies=[Depends(require_internal_access)])


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
    models: list[str] = Field(default_factory=list)


class LeavePayload(BaseModel):
    node_id: str


@router.post("/internal/register")
def register(payload: RegisterPayload, store: StateStore = Depends(get_store)):
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

    def _mutate(state):
        # Drop stale entries for the same IP (re-join with a fresh node_id
        # would otherwise leave a ghost member that pollutes rpc_hosts).
        state.members = [
            m for m in state.members
            if m.node_id == payload.node_id or m.tailscale_ip != payload.tailscale_ip
        ]
        existing_ids = {m.node_id for m in state.members}
        if payload.node_id not in existing_ids:
            state.members.append(member)
        else:
            for m in state.members:
                if m.node_id == payload.node_id:
                    m.last_seen = now
                    m.tailscale_ip = payload.tailscale_ip
                    break

    store.update(_mutate)
    return {"status": "registered", "node_id": payload.node_id}


@router.post("/internal/heartbeat")
def heartbeat(payload: HeartbeatPayload, store: StateStore = Depends(get_store)):
    def _mutate(state):
        now = datetime.now(timezone.utc)
        sweep_cutoff = now - timedelta(seconds=DEAD_SWEEP_AFTER_S)
        sender_found = False
        for member in state.members:
            if member.node_id == payload.node_id:
                member.last_seen = now
                member.connection_type = payload.connection_type
                sender_found = True
        if not sender_found:
            return False
        survivors = []
        for m in state.members:
            if m.node_id == payload.node_id or m.role == "coordinator":
                survivors.append(m)
                continue
            if m.last_seen < sweep_cutoff:
                age = int((now - m.last_seen).total_seconds())
                _log.warning(
                    "Auto-removing dead worker %s (%s) — last_seen %ds ago",
                    m.name, m.tailscale_ip, age,
                )
                continue
            survivors.append(m)
        state.members = survivors
        return True

    return {"status": "ok"} if store.update(_mutate) else {"status": "unknown_node"}


@router.post("/internal/attach")
def attach(payload: AttachPayload, store: StateStore = Depends(get_store)):
    def _mutate(state):
        for member in state.members:
            if member.node_id == payload.node_id:
                member.inference_engine = payload.inference_engine
                member.models = payload.models
                member.last_seen = datetime.now(timezone.utc)
                loaded_model = next((m for m in state.models if m.loaded), None)
                if loaded_model is not None and member.role == "worker":
                    return ("ok", loaded_model.name, loaded_model.loaded_pid)
                return ("ok", None, 0)
        return ("unknown_node", None, 0)

    status, model_name, loaded_pid = store.update(_mutate)
    if status == "ok" and model_name:
        threading.Thread(
            target=_restart_llamacpp,
            args=(model_name, loaded_pid, store),
            daemon=True,
        ).start()
    return {"status": status}


def _set_reloading(store: StateStore, model_name: str, value: bool) -> None:
    def _mutate(fresh):
        for m in fresh.models:
            if m.name == model_name:
                m.reloading = value
                break
    store.update(_mutate)


def _restart_llamacpp(model_name: str, old_pid: int, store: StateStore) -> None:
    _set_reloading(store, model_name, True)
    try:
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
        except Exception as exc:
            _log.error("LlamaCpp restart failed for model '%s': %s", model_name, exc)
            return

        loaded_pid = engine._process.pid if engine._process else 0

        def _mutate(fresh):
            for m in fresh.models:
                if m.name == model_name:
                    m.loaded = True
                    m.worker_nodes = rpc_hosts
                    m.loaded_pid = loaded_pid
                    break

        store.update(_mutate)
    finally:
        _set_reloading(store, model_name, False)


@router.post("/internal/leave")
def leave(payload: LeavePayload, store: StateStore = Depends(get_store)):
    def _mutate(state):
        target = next((m for m in state.members if m.node_id == payload.node_id), None)
        if target is None:
            return False
        if target.role == "coordinator":
            return False
        target_ip = target.tailscale_ip
        state.members = [m for m in state.members if m.node_id != payload.node_id]
        for model in state.models:
            model.worker_nodes = [w for w in model.worker_nodes if not w.startswith(f"{target_ip}:")]
        return True

    removed = store.update(_mutate)
    return {"status": "ok" if removed else "unknown_node"}


@router.get("/internal/state")
def get_state(store: StateStore = Depends(get_store)):
    state = store.load()
    data = state.model_dump()
    for key_entry in data.get("keys", []):
        key_entry.pop("key_hash", None)
        key_entry.pop("key", None)
    return data
