import json
import os
import threading
from pathlib import Path

from .schema import PodState
from ..errors import StateError

USAGE_LIMIT = 1000
STATE_PATH = Path.home() / ".pods" / "state.json"
_write_lock = threading.RLock()


class StateStore:
    def __init__(self, path: Path = STATE_PATH):
        self.path = Path(path)

    def load(self) -> PodState:
        try:
            data = json.loads(self.path.read_text())
            return PodState.model_validate(data)
        except FileNotFoundError:
            raise StateError(
                "state.json not found",
                reason=f"Expected at {self.path}",
                suggestion="Run 'pods init' on the coordinator first",
            )
        except Exception as e:
            raise StateError(
                "state.json is malformed",
                reason=str(e),
                suggestion="Run 'pods status' to diagnose or restore from backup",
            )

    def save(self, state: PodState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with _write_lock:
            tmp.write_text(state.model_dump_json(indent=2))
            os.replace(tmp, self.path)

    def trim_usage(self, state: PodState) -> PodState:
        if len(state.usage) > USAGE_LIMIT:
            state.usage = state.usage[-USAGE_LIMIT:]
        return state
