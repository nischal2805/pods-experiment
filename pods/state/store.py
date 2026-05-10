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

    @property
    def _backup_path(self) -> Path:
        return self.path.with_suffix(".json.bak")

    def _try_load_path(self, path: Path) -> PodState:
        data = json.loads(path.read_text())
        return PodState.model_validate(data)

    def load(self) -> PodState:
        if not self.path.exists():
            raise StateError(
                "state.json not found",
                reason=f"Expected at {self.path}",
                suggestion="Run 'pods init' on the coordinator first",
            )
        try:
            state = self._try_load_path(self.path)
        except Exception as primary_err:
            backup = self._backup_path
            if backup.exists():
                try:
                    state = self._try_load_path(backup)
                    print(f"[pods] WARN: state.json corrupt — recovered from {backup.name}")
                    self.save(state)
                except Exception:
                    raise StateError(
                        "state.json and backup are both malformed",
                        reason=str(primary_err),
                        suggestion="Re-run 'pods init' or restore manually from logs",
                    )
            else:
                raise StateError(
                    "state.json is malformed",
                    reason=str(primary_err),
                    suggestion="Run 'pods status' to diagnose or restore from backup",
                )
        if self._migrate_legacy_keys(state):
            self.save(state)
        return state

    def save(self, state: PodState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with _write_lock, _file_lock(self.path):
            tmp.write_text(state.model_dump_json(indent=2))
            if self.path.exists():
                try:
                    import shutil
                    shutil.copy2(self.path, self._backup_path)
                except Exception:
                    pass  # backup is best-effort
            os.replace(tmp, self.path)

    def update(self, mutator: Callable[[PodState], T]) -> T:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with _write_lock, _file_lock(self.path):
            if not self.path.exists():
                raise StateError(
                    "state.json not found",
                    reason=f"Expected at {self.path}",
                    suggestion="Run 'pods init' on the coordinator first",
                )
            try:
                state = self._try_load_path(self.path)
            except Exception as e:
                raise StateError(
                    "state.json is malformed",
                    reason=str(e),
                    suggestion="Run 'pods status' to diagnose or restore from backup",
                )
            result = mutator(state)
            tmp.write_text(state.model_dump_json(indent=2))
            try:
                import shutil
                shutil.copy2(self.path, self._backup_path)
            except Exception:
                pass
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
