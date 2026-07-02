import json
import time

import httpx
from fastapi.responses import StreamingResponse

from ..errors import InferenceError

CONNECT_TIMEOUT_S = 10.0
# Per-chunk read timeout — must cover slow prefill on large models before the
# first token arrives, not the total stream duration.
READ_TIMEOUT_S = 300.0


async def stream_to_backend(
    backend_url: str,
    request_body: dict,
    timeout: httpx.Timeout | float | None = None,
) -> tuple[StreamingResponse, dict]:
    request_body = {**request_body, "stream": True}
    usage_info = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0}
    start = time.time()

    if timeout is None:
        timeout = httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)

    client = httpx.AsyncClient(timeout=timeout)
    try:
        req = client.build_request(
            "POST",
            f"{backend_url}/v1/chat/completions",
            json=request_body,
        )
        resp = await client.send(req, stream=True)
    except httpx.TimeoutException as e:
        await client.aclose()
        raise InferenceError(
            "Backend request timed out",
            reason=str(e),
            suggestion="Try again or run 'pods model load <name>' to reload the model",
        )
    except httpx.HTTPError as e:
        await client.aclose()
        raise InferenceError(
            "Cannot connect to inference backend",
            reason=str(e),
            suggestion="Run 'pods attach' to start the inference backend",
        )

    if resp.status_code >= 400:
        body = await resp.aread()
        await resp.aclose()
        await client.aclose()
        raise InferenceError(
            f"Backend returned HTTP {resp.status_code}",
            reason=body.decode("utf-8", errors="replace")[:500],
            suggestion="Check the model name and the backend log in ~/.pods/logs/",
        )

    first_token = True

    async def generate():
        nonlocal first_token
        try:
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    if first_token:
                        usage_info["latency_ms"] = int((time.time() - start) * 1000)
                        first_token = False
                    try:
                        data = json.loads(line[6:])
                        if "usage" in data and data["usage"]:
                            usage_info["prompt_tokens"] = data["usage"].get("prompt_tokens", 0)
                            usage_info["completion_tokens"] = data["usage"].get("completion_tokens", 0)
                    except (json.JSONDecodeError, KeyError):
                        pass
                yield f"{line}\n"
        finally:
            await resp.aclose()
            await client.aclose()

    return StreamingResponse(generate(), media_type="text/event-stream"), usage_info
