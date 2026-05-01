from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class Key(BaseModel):
    key: str
    label: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    total_requests: int = 0
    total_tokens: int = 0


class UsageRecord(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    key: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    backend: str  # "llamacpp" | "exo" | "ollama"
    latency_ms: int


class Model(BaseModel):
    name: str
    file: str
    size_gb: float
    added_at: datetime = Field(default_factory=datetime.utcnow)
    loaded: bool = False
    worker_nodes: list[str] = Field(default_factory=list)


class Member(BaseModel):
    node_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tailscale_ip: str
    role: str  # "coordinator" | "worker"
    os: str  # "linux" | "wsl2" | "mac" | "windows"
    gpu_vram_gb: int = 0
    inference_engine: str = "none"  # "llamacpp_rpc" | "exo" | "ollama" | "none"
    connection_type: str = "relay"  # "direct" | "relay"
    models: list[str] = Field(default_factory=list)
    joined_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen: datetime = Field(default_factory=datetime.utcnow)


class Pod(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    coordinator_ip: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    inference_engine: str = "llamacpp"  # "llamacpp" | "exo" | "ollama"


class PodState(BaseModel):
    pod: Pod
    members: list[Member] = Field(default_factory=list)
    keys: list[Key] = Field(default_factory=list)
    usage: list[UsageRecord] = Field(default_factory=list)
    models: list[Model] = Field(default_factory=list)
