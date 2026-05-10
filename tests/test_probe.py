import socket
import threading

import pytest

from pods.network.probe import tcp_probe, tcp_probe_many


@pytest.fixture
def listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]

    stop = threading.Event()

    def serve():
        s.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = s.accept()
                conn.close()
            except socket.timeout:
                continue
            except OSError:
                return

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield port
    stop.set()
    s.close()
    t.join(timeout=1)


def test_probe_open_port(listener):
    assert tcp_probe("127.0.0.1", listener, timeout=1.0) is True


def test_probe_closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert tcp_probe("127.0.0.1", port, timeout=0.5) is False


def test_probe_unreachable_host():
    # 192.0.2.0/24 is RFC 5737 TEST-NET-1 — guaranteed non-routable
    assert tcp_probe("192.0.2.1", 12345, timeout=0.5) is False


def test_probe_many_empty():
    assert tcp_probe_many([]) == {}


def test_probe_many_mixed(listener):
    s_closed = socket.socket()
    s_closed.bind(("127.0.0.1", 0))
    closed_port = s_closed.getsockname()[1]
    s_closed.close()

    results = tcp_probe_many(
        [("127.0.0.1", listener), ("127.0.0.1", closed_port)],
        timeout=0.5,
    )
    assert results[("127.0.0.1", listener)] is True
    assert results[("127.0.0.1", closed_port)] is False
