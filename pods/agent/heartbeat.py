import threading

import httpx

from ..internal_auth import internal_headers

def _send_heartbeat(coordinator_url: str, node_id: str, connection_type: str = "relay") -> None:
    try:
        response = httpx.post(
            f"{coordinator_url}/internal/heartbeat",
            json={"node_id": node_id, "connection_type": connection_type},
            headers=internal_headers(),
            timeout=5,
        )
        response.raise_for_status()
    except Exception as e:
        print(f"[pods] Warning: heartbeat failed: {e}")


class HeartbeatThread(threading.Thread):
    """Daemon thread that POSTs /internal/heartbeat every 30 seconds."""

    def __init__(self, coordinator_url: str, node_id: str, interval: int = 30):
        super().__init__(daemon=True)
        self.coordinator_url = coordinator_url
        self.node_id = node_id
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            _send_heartbeat(self.coordinator_url, self.node_id)

    def stop(self) -> None:
        self._stop_event.set()
