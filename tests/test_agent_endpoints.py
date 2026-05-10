from unittest.mock import MagicMock

from pods.agent import server


def test_stop_rpc_when_running(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr(server, "_engine", engine)
    resp = server.stop_rpc(_=None)
    assert resp == {"status": "stopped"}
    engine.stop.assert_called_once()
    assert server._engine is None


def test_stop_rpc_when_not_running(monkeypatch):
    monkeypatch.setattr(server, "_engine", None)
    resp = server.stop_rpc(_=None)
    assert resp == {"status": "not_running"}


def test_shutdown_stops_engine_and_schedules_exit(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr(server, "_engine", engine)

    started_threads = []
    class _FakeThread:
        def __init__(self, target, daemon):
            self.target = target
            self.daemon = daemon
        def start(self):
            started_threads.append(self.target)

    monkeypatch.setattr(server.threading, "Thread", _FakeThread)

    resp = server.shutdown(_=None)
    assert resp == {"status": "shutting_down"}
    engine.stop.assert_called_once()
    assert server._engine is None
    assert len(started_threads) == 1


def test_shutdown_no_engine(monkeypatch):
    monkeypatch.setattr(server, "_engine", None)

    started = []
    class _FakeThread:
        def __init__(self, target, daemon):
            self.target = target
        def start(self):
            started.append(True)

    monkeypatch.setattr(server.threading, "Thread", _FakeThread)

    resp = server.shutdown(_=None)
    assert resp == {"status": "shutting_down"}
    assert started == [True]
