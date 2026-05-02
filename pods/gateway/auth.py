from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..state.schema import Key
from ..state.store import StateStore
from ..state.defaults import verify_key

_bearer = HTTPBearer()


def validate_api_key(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
    store: StateStore = Depends(StateStore),
) -> Key:
    token = credentials.credentials
    try:
        state = store.load()
    except Exception:
        raise HTTPException(status_code=503, detail="State unavailable")

    for key in state.keys:
        if key.key_hash and verify_key(token, key.key_hash):
            return key

    raise HTTPException(
        status_code=401,
        detail={
            "error": "Invalid or missing API key",
            "suggestion": "Run 'pods keygen <label>' on the coordinator to generate a key",
        },
    )
