"""The watch loop's decisions, without a cluster or a db."""

import pytest
import yaml

from harness.config import ConfigError
from harness.orchestrator.watch import creds_tick, read_published
from harness.results.db import NullResults, Results


def _config_yaml(name="bench"):
    return yaml.safe_dump({
        "global": {"name": name, "task": "tasks/smoke", "model": "haiku",
                   "source": {"repo": "https://x/y.git", "ref": "a" * 40},
                   "neon": {"project": "proj"}},
        "runs": [{"id": "1"}],
    })


def test_nothing_published_is_none(tmp_path):
    assert read_published(tmp_path) is None
    (tmp_path / "fanout.yaml").write_text(_config_yaml())
    assert read_published(tmp_path) is None  # no stamp yet
    (tmp_path / "stamp").write_text("")
    assert read_published(tmp_path) is None  # empty stamp is no stamp


def test_published_config_parses_with_its_stamp(tmp_path):
    (tmp_path / "fanout.yaml").write_text(_config_yaml())
    (tmp_path / "stamp").write_text("0728120000\n")
    stamp, cfg = read_published(tmp_path)
    assert stamp == "0728120000"
    assert cfg.name == "bench" and len(cfg.runs) == 1


def test_a_published_typo_is_loud_not_idle(tmp_path):
    (tmp_path / "fanout.yaml").write_text("global:\n  modle: haiku\nruns: [{id: '1'}]\n")
    (tmp_path / "stamp").write_text("0728120000")
    with pytest.raises(ConfigError):
        read_published(tmp_path)


def test_missing_creds_log_says_how_to_fix_it(tmp_path):
    lines = []
    creds_tick(tmp_path, namespace="multirun", secret="claude-creds",
               log=lines.append)
    assert lines and "creds push" in lines[0]


def test_fresh_creds_stay_quiet(tmp_path):
    _write_creds(tmp_path, expires_in_s=7200)
    lines = []
    creds_tick(tmp_path, namespace="multirun", secret="claude-creds",
               log=lines.append)
    assert lines == []


def _write_creds(tmp_path, expires_in_s):
    import json
    import time
    (tmp_path / ".credentials.json").write_text(json.dumps(
        {"claudeAiOauth": {"expiresAt": (time.time() + expires_in_s) * 1000}}))


def test_probe_that_authenticates_is_one_line_then_quiet(tmp_path, monkeypatch):
    """Near-expiry creds whose file never rotates used to nag every
    tick — and burn a CLI turn every tick doing it."""
    _write_creds(tmp_path, expires_in_s=60)
    turns = []
    monkeypatch.setattr("harness.orchestrator.controller.refresh_creds",
                        lambda d: turns.append(d) or (True, None))
    lines, state = [], {}
    for _ in range(3):
        creds_tick(tmp_path, namespace="multirun", secret="claude-creds",
                   log=lines.append, state=state)
    assert len(turns) == 1  # cooldown holds: one probe, not one per tick
    assert len(lines) == 1 and "healthy" in lines[0]


def test_probe_that_cannot_authenticate_is_loud(tmp_path, monkeypatch):
    _write_creds(tmp_path, expires_in_s=60)
    monkeypatch.setattr("harness.orchestrator.controller.refresh_creds",
                        lambda d: (False, None))
    lines = []
    creds_tick(tmp_path, namespace="multirun", secret="claude-creds",
               log=lines.append, state={})
    assert "REFRESH FAILED" in lines[0] and "creds push" in lines[0]


def test_rotated_creds_are_pushed_back_into_the_secret(tmp_path, monkeypatch):
    _write_creds(tmp_path, expires_in_s=60)
    monkeypatch.setattr("harness.orchestrator.controller.refresh_creds",
                        lambda d: (True, '{"rotated": true}'))
    pushed = {}
    monkeypatch.setattr(
        "harness.orchestrator.watch._patch_creds_secret",
        lambda name, ns, content: pushed.update(name=name, content=content))
    lines = []
    creds_tick(tmp_path, namespace="multirun", secret="claude-creds",
               log=lines.append, state={})
    assert pushed == {"name": "claude-creds", "content": '{"rotated": true}'}
    assert "pushed back" in lines[0]


def test_replaced_creds_file_resets_the_cooldown(tmp_path, monkeypatch):
    """`multirun creds push` mid-cooldown lands new content; the next
    tick must probe it instead of sitting out the clock."""
    _write_creds(tmp_path, expires_in_s=60)
    turns = []
    monkeypatch.setattr("harness.orchestrator.controller.refresh_creds",
                        lambda d: turns.append(d) or (True, None))
    state: dict = {}
    creds_tick(tmp_path, namespace="multirun", secret="claude-creds",
               log=lambda _: None, state=state)
    _write_creds(tmp_path, expires_in_s=90)  # different content, still stale
    creds_tick(tmp_path, namespace="multirun", secret="claude-creds",
               log=lambda _: None, state=state)
    assert len(turns) == 2


def test_no_results_db_means_no_memory_and_no_crash():
    results = Results.open(None)
    assert isinstance(results, NullResults)
    assert results.fanout_exists("anything") is False


def test_results_retry_reconnects_a_dead_connection(monkeypatch):
    """Neon idles long-lived connections out; one dead-connection retry
    against a fresh connection keeps the watch loop alive."""
    import types

    class FakeOperationalError(Exception):
        pass

    calls = {"connect": 0}

    class FakeConn:
        def close(self):
            pass

    def fake_connect(uri, autocommit):
        calls["connect"] += 1
        return FakeConn()

    fake_psycopg = types.SimpleNamespace(OperationalError=FakeOperationalError,
                                         connect=fake_connect)
    import sys
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    r = Results("postgresql://fake")
    assert calls["connect"] == 1

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise FakeOperationalError("SSL connection has been closed")
        return "ok"

    assert r._retry(flaky) == "ok"
    assert calls["connect"] == 2  # reconnected before the second attempt
