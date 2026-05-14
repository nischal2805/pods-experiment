import secrets
import string
import hashlib
import hmac

from .schema import Key, Member, Pod


def new_pod(name: str, coordinator_ip: str) -> Pod:
    return Pod(name=name, coordinator_ip=coordinator_ip)


def new_member(
    name: str,
    tailscale_ip: str,
    role: str,
    os: str,
    gpu_vram_gb: int = 0,
) -> Member:
    return Member(
        name=name,
        tailscale_ip=tailscale_ip,
        role=role,
        os=os,
        gpu_vram_gb=gpu_vram_gb,
    )


def new_key(label: str) -> Key:
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(32))
    raw_key = f"pk_{random_part}"
    return Key(
        key_id=key_id_from_token(raw_key),
        key_hash=hash_key(raw_key),
        label=label,
    )


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def verify_key(raw_key: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_key(raw_key), key_hash)


def key_id_from_token(raw_key: str) -> str:
    # Use a hash of the key so the key_id shown in logs/status leaks no key bytes.
    # Existing keys already have their key_id stored in state.json, so changing this
    # only affects newly created keys.
    return "kid_" + hashlib.sha256(raw_key.encode()).hexdigest()[:8]


def new_raw_key(label: str) -> tuple[str, Key]:
    alphabet = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(alphabet) for _ in range(32))
    raw_key = f"pk_{random_part}"
    return raw_key, Key(
        key_id=key_id_from_token(raw_key),
        key_hash=hash_key(raw_key),
        label=label,
    )
