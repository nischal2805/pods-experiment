import base64
import json
import time

from ..errors import NetworkError

INVITE_EXPIRY_SECONDS = 86400  # 24 hours


def encode_invite(coordinator_ip: str, pod_name: str, internal_token: str) -> str:
    payload = json.dumps({
        "coordinator_ip": coordinator_ip,
        "pod_name": pod_name,
        "internal_token": internal_token,
        "expires_at": time.time() + INVITE_EXPIRY_SECONDS,
    })
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_invite(link: str) -> dict:
    try:
        data = base64.urlsafe_b64decode(link.encode()).decode()
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("Payload is not a JSON object")
        required = {"coordinator_ip", "pod_name", "internal_token"}
        missing = required - parsed.keys()
        if missing:
            raise ValueError(f"Missing fields: {missing}")
        expires_at = parsed.get("expires_at")
        if expires_at is not None and time.time() > expires_at:
            raise ValueError("Invite link has expired (valid for 24 hours) — run 'pods invite' again")
        return parsed
    except Exception as e:
        raise NetworkError(
            "Invalid invite link",
            reason=str(e),
            suggestion="Ask the coordinator to run 'pods invite' again",
        )
