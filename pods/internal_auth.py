import hmac
import json
import os
from pathlib import Path

from fastapi import HTTPException, Request

CONFIG_PATH = Path.home() / ".pods" / "config.json"
HEADER_NAME = "x-pods-internal-key"
ENV_NAME = "PODS_INTERNAL_TOKEN"


def read_internal_token() -> str | None:
    token = os.environ.get(ENV_NAME)
    if token:
        return token
    try:
        config = json.loads(CONFIG_PATH.read_text())
    except Exception:
        return None
    value = config.get("internal_token")
    return value if isinstance(value, str) and value else None


def internal_headers() -> dict[str, str]:
    token = read_internal_token()
    if not token:
        return {}
    return {HEADER_NAME: token}


def require_internal_access(request: Request) -> None:
    host = request.client.host if request.client else ""
    if not (host.startswith("100.") or host in ("127.0.0.1", "::1")):
        raise HTTPException(
            status_code=403,
            detail="Internal endpoints require Tailscale network access",
        )

    expected = read_internal_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Internal auth token is not configured on this node",
        )

    provided = request.headers.get(HEADER_NAME, "")
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid internal auth token")
