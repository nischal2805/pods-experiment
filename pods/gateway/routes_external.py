import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from ..state.schema import Key, UsageRecord
from ..state.store import StateStore
from ..errors import InferenceError
from .auth import validate_api_key
from .router import select_backend
from .proxy import stream_to_backend

router = APIRouter()

RELOAD_RETRY_AFTER_S = 5

# Simple in-memory sliding-window rate limiter: 60 requests per minute per API key.
RATE_LIMIT_RPM = 60
RATE_WINDOW_S = 60.0
_rate_counters: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


def _is_rate_limited(key_id: str) -> bool:
    now = time.time()
    with _rate_lock:
        timestamps = _rate_counters.get(key_id, [])
        timestamps = [t for t in timestamps if now - t < RATE_WINDOW_S]
        if not timestamps:
            # All prior timestamps expired — evict the entry to prevent unbounded dict growth
            # when keys go idle after a burst.
            _rate_counters.pop(key_id, None)
        if len(timestamps) >= RATE_LIMIT_RPM:
            _rate_counters[key_id] = timestamps
            return True
        timestamps.append(now)
        _rate_counters[key_id] = timestamps
        return False


def get_store() -> StateStore:
    return StateStore()


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    key: Key = Depends(validate_api_key),
    store: StateStore = Depends(get_store),
):
    if _is_rate_limited(key.key_id):
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(int(RATE_WINDOW_S))},
            content={"error": "rate_limit_exceeded", "retry_after_s": int(RATE_WINDOW_S)},
        )

    body = await request.json()
    model = body.get("model", "")

    try:
        state = store.load()
    except Exception:
        raise HTTPException(status_code=503, detail="State unavailable")

    target = next((m for m in state.models if m.name == model and m.loaded), None)
    if target is not None and target.reloading:
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": str(RELOAD_RETRY_AFTER_S)},
            content={"error": "model reloading", "retry_after_s": RELOAD_RETRY_AFTER_S},
        )

    try:
        backend_name, backend_url = select_backend(model, state)
    except InferenceError as e:
        raise HTTPException(status_code=503, detail={"error": e.message, "reason": e.reason, "suggestion": e.suggestion})

    try:
        response, usage_info = await stream_to_backend(backend_url, body)
    except InferenceError as e:
        raise HTTPException(status_code=503, detail={"error": e.message, "reason": e.reason, "suggestion": e.suggestion})

    async def _record_usage():
        try:
            def _mutate(s):
                record = UsageRecord(
                    key_id=key.key_id,
                    model=model,
                    prompt_tokens=usage_info["prompt_tokens"],
                    completion_tokens=usage_info["completion_tokens"],
                    backend=backend_name,
                    latency_ms=usage_info["latency_ms"],
                )
                s.usage.append(record)
                s = store.trim_usage(s)
                for k in s.keys:
                    if k.key_id == key.key_id:
                        k.total_requests += 1
                        k.total_tokens += usage_info["prompt_tokens"] + usage_info["completion_tokens"]
                        break

            store.update(_mutate)
        except Exception as e:
            print(f"[pods] Warning: failed to record usage: {e}")

    response.background = BackgroundTask(_record_usage)
    return response


@router.get("/v1/models")
async def list_models(
    _: Key = Depends(validate_api_key),
    store: StateStore = Depends(get_store),
):
    try:
        state = store.load()
    except Exception:
        raise HTTPException(status_code=503, detail="State unavailable")

    data = [
        {"id": m.name, "object": "model", "created": 0, "owned_by": "pods"}
        for m in state.models
    ]
    return {"object": "list", "data": data}
