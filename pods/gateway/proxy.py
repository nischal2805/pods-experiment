import json
import time

import httpx
from fastapi.responses import StreamingResponse

from ..errors import InferenceError


async def stream_to_backend(
    backend_url: str,
    request_body: dict,
    timeout: float = 30.0,
) -> tuple[StreamingResponse, dict]:
    request_body = {**request_body, "stream": True}
    usage_info = {"prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0}
    start = time.time()
    first_token = True

    async def generate():
        nonlocal first_token
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{backend_url}/v1/chat/completions",
                    json=request_body,
                ) as resp:
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
        except httpx.TimeoutException as e:
            raise InferenceError(
                "Backend request timed out",
                reason=str(e),
                suggestion="Try again or run 'pods model load <name>' to reload the model",
            )
        except httpx.ConnectError as e:
            raise InferenceError(
                "Cannot connect to inference backend",
                reason=str(e),
                suggestion="Run 'pods attach' to start the inference backend",
            )

    return StreamingResponse(generate(), media_type="text/event-stream"), usage_info
