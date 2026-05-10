from datetime import datetime, timezone, timedelta

from pods.cli.status import _label_for
from pods.state.schema import Member


def _worker(ip="100.0.0.2", last_seen_ago_s=10):
    return Member(
        name="w1",
        tailscale_ip=ip,
        role="worker",
        os="linux",
        last_seen=datetime.now(timezone.utc) - timedelta(seconds=last_seen_ago_s),
    )


def test_label_ok_when_fresh_and_ports_up():
    m = _worker(last_seen_ago_s=5)
    probes = {("100.0.0.2", 8082): True, ("100.0.0.2", 50052): True}
    assert _label_for(m, probes, datetime.now(timezone.utc)) == "OK"


def test_label_degraded_when_agent_down():
    m = _worker(last_seen_ago_s=5)
    probes = {("100.0.0.2", 8082): False, ("100.0.0.2", 50052): True}
    assert _label_for(m, probes, datetime.now(timezone.utc)) == "DEGRADED"


def test_label_degraded_when_rpc_down():
    m = _worker(last_seen_ago_s=5)
    probes = {("100.0.0.2", 8082): True, ("100.0.0.2", 50052): False}
    assert _label_for(m, probes, datetime.now(timezone.utc)) == "DEGRADED"


def test_label_stale_when_old_heartbeat():
    m = _worker(last_seen_ago_s=120)
    probes = {("100.0.0.2", 8082): True, ("100.0.0.2", 50052): True}
    assert _label_for(m, probes, datetime.now(timezone.utc)) == "STALE"


def test_label_dead_when_very_old():
    m = _worker(last_seen_ago_s=700)
    probes = {("100.0.0.2", 8082): False, ("100.0.0.2", 50052): False}
    assert _label_for(m, probes, datetime.now(timezone.utc)) == "DEAD"


def test_label_coordinator_always_ok():
    coord = Member(
        name="c", tailscale_ip="100.0.0.1", role="coordinator", os="linux",
        last_seen=datetime.now(timezone.utc) - timedelta(seconds=999),
    )
    assert _label_for(coord, {}, datetime.now(timezone.utc)) == "OK"
