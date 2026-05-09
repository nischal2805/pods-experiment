import base64
import json

from ..errors import NetworkError


def encode_invite(coordinator_ip: str, pod_name: str, internal_token: str) -> str:
    payload = json.dumps({
        "coordinator_ip": coordinator_ip,
        "pod_name": pod_name,
        "internal_token": internal_token,
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
        return parsed
    except Exception as e:
        raise NetworkError(
            "Invalid invite link",
            reason=str(e),
            suggestion="Ask the coordinator to run 'pods invite' again",
        )
