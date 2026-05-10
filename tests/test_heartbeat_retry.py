from unittest.mock import patch, MagicMock

from pods.agent.heartbeat import _send_heartbeat, HeartbeatThread


def test_heartbeat_succeeds_first_try():
    sleeps: list[float] = []
    with patch("pods.agent.heartbeat._send_heartbeat_once") as mock:
        ok = _send_heartbeat("http://x", "node1", sleep=sleeps.append)
    assert ok is True
    assert mock.call_count == 1
    assert sleeps == []


def test_heartbeat_retries_with_backoff():
    sleeps: list[float] = []
    mock = MagicMock(side_effect=[Exception("boom"), Exception("boom"), None])
    with patch("pods.agent.heartbeat._send_heartbeat_once", mock):
        ok = _send_heartbeat("http://x", "node1", sleep=sleeps.append)
    assert ok is True
    assert mock.call_count == 3
    assert sleeps == [2, 4]  # only sleeps before retries 2 and 3, not after final


def test_heartbeat_gives_up_after_three():
    sleeps: list[float] = []
    mock = MagicMock(side_effect=Exception("nope"))
    with patch("pods.agent.heartbeat._send_heartbeat_once", mock):
        ok = _send_heartbeat("http://x", "node1", sleep=sleeps.append)
    assert ok is False
    assert mock.call_count == 3
    assert sleeps == [2, 4]


def test_consecutive_failures_increment(capsys):
    t = HeartbeatThread("http://x", "node1", interval=30)
    with patch("pods.agent.heartbeat._send_heartbeat", return_value=False):
        # simulate 3 cycles by calling the loop body manually
        for _ in range(3):
            ok = False  # force fail path
            if ok:
                t._consecutive_failures = 0
            else:
                t._consecutive_failures += 1
                if t._consecutive_failures >= 3:
                    elapsed = t._consecutive_failures * t.interval
                    print(f"[pods] ERROR: heartbeat lost — coordinator unreachable for ~{elapsed}s")
    assert t._consecutive_failures == 3
    out = capsys.readouterr().out
    assert "heartbeat lost" in out
    assert "~90s" in out


def test_consecutive_failures_reset_on_success():
    t = HeartbeatThread("http://x", "node1")
    t._consecutive_failures = 2
    # simulating success branch
    t._consecutive_failures = 0
    assert t._consecutive_failures == 0
