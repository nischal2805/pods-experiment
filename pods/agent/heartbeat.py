import threading
import time
from typing import Callable

import httpx

from ..internal_auth import internal_headers

RETRY_BACKOFFS = (2, 4, 8)
MAX_CONSECUTIVE_FAILURES_BEFORE_ERROR = 3


def _send_heartbeat_once(coordinator_url: str, node_id: str, connection_type: str = "relay") -> None:
    response = httpx.post(
        f"{coordinator_url}/internal/heartbeat",
        json={"node_id": node_id, "connection_type": connection_type},
        headers=internal_headers(),
        timeout=5,
    )
    response.raise_for_status()


def _send_heartbeat(
    coordinator_url: str,
    node_id: str,
    connection_type: str = "relay",
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    last_err: Exception | None = None
    for attempt, backoff in enumerate(RETRY_BACKOFFS, start=1):
        try:
            _send_heartbeat_once(coordinator_url, node_id, connection_type)
            return True
        except Exception as e:
            last_err = e
            print(f"[pods] WARN: heartbeat failed (attempt {attempt}/{len(RETRY_BACKOFFS)}): {e}")
            if attempt < len(RETRY_BACKOFFS):
                sleep(backoff)
    print(f"[pods] WARN: heartbeat cycle gave up after {len(RETRY_BACKOFFS)} attempts: {last_err}")
    return False


class HeartbeatThread(threading.Thread):
    """Daemon thread that POSTs /internal/heartbeat every interval seconds with retry+backoff."""

    def __init__(self, coordinator_url: str, node_id: str, interval: int = 30):
        super().__init__(daemon=True)
        self.coordinator_url = coordinator_url
        self.node_id = node_id
        self.interval = interval
        self._stop_event = threading.Event()
        self._consecutive_failures = 0

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            ok = _send_heartbeat(self.coordinator_url, self.node_id)
            if ok:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES_BEFORE_ERROR:
                    elapsed = self._consecutive_failures * self.interval
                    print(
                        f"[pods] ERROR: heartbeat lost — coordinator unreachable for ~{elapsed}s "
                        f"({self._consecutive_failures} consecutive cycle failures)"
                    )

    def stop(self) -> None:
        self._stop_event.set()
