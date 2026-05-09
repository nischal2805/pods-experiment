from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.background import BackgroundTask

from ..state.schema import Key, UsageRecord
from ..state.store import StateStore
from ..errors import InferenceError
from .auth import validate_api_key
from .router import select_backend
from .proxy import stream_to_backend

router = APIRouter()


def get_store() -> StateStore:
    return StateStore()


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    key: Key = Depends(validate_api_key),
    store: StateStore = Depends(get_store),
):
    body = await request.json()
    model = body.get("model", "")

    try:
        state = store.load()
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
