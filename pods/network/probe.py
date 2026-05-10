import socket
from concurrent.futures import ThreadPoolExecutor


def tcp_probe(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def tcp_probe_many(
    targets: list[tuple[str, int]],
    timeout: float = 1.0,
    max_workers: int = 8,
) -> dict[tuple[str, int], bool]:
    if not targets:
        return {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(tcp_probe, h, p, timeout): (h, p) for h, p in targets}
        return {futures[f]: f.result() for f in futures}
