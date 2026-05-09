import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, TypeVar

from .schema import PodState
from .defaults import hash_key, key_id_from_token
from ..errors import StateError

USAGE_LIMIT = 1000
STATE_PATH = Path.home() / ".pods" / "state.json"
_write_lock = threading.RLock()
T = TypeVar("T")


@contextmanager
def _file_lock(path: Path):
    try:
        import fcntl
        lock_path = path.with_suffix(".json.lock")
        lf = open(lock_path, "w")
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            lf.close()
    except ImportError:
        import msvcrt
        lock_path = path.with_suffix(".json.lock")
        lf = open(lock_path, "a+")
        try:
            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            lf.seek(0)
            msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)
            lf.close()


class StateStore:
    def __init__(self, path: Path = STATE_PATH):
        self.path = Path(path)

    def load(self) -> PodState:
        try:
            data = json.loads(self.path.read_text())
            state = PodState.model_validate(data)
            if self._migrate_legacy_keys(state):
                self.save(state)
            return state
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
        with _write_lock, _file_lock(self.path):
            tmp.write_text(state.model_dump_json(indent=2))
            os.replace(tmp, self.path)

    def update(self, mutator: Callable[[PodState], T]) -> T:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with _write_lock, _file_lock(self.path):
            try:
                data = json.loads(self.path.read_text())
                state = PodState.model_validate(data)
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
            result = mutator(state)
            tmp.write_text(state.model_dump_json(indent=2))
            os.replace(tmp, self.path)
            return result

    def trim_usage(self, state: PodState) -> PodState:
        if len(state.usage) > USAGE_LIMIT:
            state.usage = state.usage[-USAGE_LIMIT:]
        return state

    @staticmethod
    def _migrate_legacy_keys(state: PodState) -> bool:
        changed = False
        for key in state.keys:
            if key.key:
                key.key_id = key_id_from_token(key.key)
                key.key_hash = hash_key(key.key)
                key.key = None
                changed = True
        return changed
