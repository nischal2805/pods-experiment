import secrets
import string

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
    return Key(key=f"pk_{random_part}", label=label)
