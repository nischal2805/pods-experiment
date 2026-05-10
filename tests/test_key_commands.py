from click.testing import CliRunner

from pods.cli.key import cmd as key_cmd
from pods.state.defaults import new_raw_key
from pods.state.schema import Pod, PodState
from pods.state.store import StateStore


def _state(keys=None):
    return PodState(pod=Pod(name="t", coordinator_ip="100.0.0.1"), keys=keys or [])


def test_list_empty(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    store.save(_state())
    monkeypatch.setattr("pods.cli.key.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(key_cmd, ["list"])
    assert result.exit_code == 0
    assert "No API keys" in result.output


def test_list_shows_keys(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    _, k1 = new_raw_key("alpha")
    _, k2 = new_raw_key("beta")
    store.save(_state(keys=[k1, k2]))
    monkeypatch.setattr("pods.cli.key.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(key_cmd, ["list"])
    assert result.exit_code == 0
    assert "alpha" in result.output
    assert "beta" in result.output


def test_revoke_by_label(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    _, k1 = new_raw_key("alpha")
    _, k2 = new_raw_key("beta")
    store.save(_state(keys=[k1, k2]))
    monkeypatch.setattr("pods.cli.key.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(key_cmd, ["revoke", "alpha", "--yes"])
    assert result.exit_code == 0, result.output
    assert "Revoked 'alpha'" in result.output

    after = store.load()
    assert {k.label for k in after.keys} == {"beta"}


def test_revoke_by_full_token(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    raw, k1 = new_raw_key("alpha")
    store.save(_state(keys=[k1]))
    monkeypatch.setattr("pods.cli.key.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(key_cmd, ["revoke", raw, "--yes"])
    assert result.exit_code == 0, result.output

    after = store.load()
    assert after.keys == []


def test_revoke_unknown(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    _, k1 = new_raw_key("alpha")
    store.save(_state(keys=[k1]))
    monkeypatch.setattr("pods.cli.key.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(key_cmd, ["revoke", "nonexistent", "--yes"])
    assert result.exit_code == 1
    assert "No key matches" in result.output


def test_revoke_ambiguous_label(tmp_path, monkeypatch):
    store = StateStore(path=tmp_path / "state.json")
    _, k1 = new_raw_key("dup")
    _, k2 = new_raw_key("dup")
    store.save(_state(keys=[k1, k2]))
    monkeypatch.setattr("pods.cli.key.StateStore", lambda: store)

    runner = CliRunner()
    result = runner.invoke(key_cmd, ["revoke", "dup", "--yes"])
    assert result.exit_code == 1
    assert "Ambiguous" in result.output

    after = store.load()
    assert len(after.keys) == 2  # nothing removed
