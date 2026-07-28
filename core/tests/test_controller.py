"""Controller helpers that must be right before the cluster exists."""

import json
import time

from harness.orchestrator.controller import _resolve_task_dir, creds_stale


def _creds(expires_in_s):
    return json.dumps({"claudeAiOauth":
                       {"expiresAt": (time.time() + expires_in_s) * 1000}})


def test_fresh_creds_are_fresh():
    assert creds_stale(_creds(7200), horizon_s=3600) is False


def test_expiring_and_expired_creds_are_stale():
    assert creds_stale(_creds(600), horizon_s=3600) is True
    assert creds_stale(_creds(-600), horizon_s=3600) is True


def test_unreadable_creds_are_stale_not_a_crash():
    assert creds_stale("not json") is True
    assert creds_stale("{}") is True


def test_task_dir_resolves_relative_to_the_config(tmp_path):
    (tmp_path / "tasks" / "smoke").mkdir(parents=True)
    (tmp_path / "tasks" / "smoke" / "task.md").write_text("do it")
    (tmp_path / "core" / "configs").mkdir(parents=True)
    config = tmp_path / "core" / "configs" / "smoke.yaml"
    config.write_text("global: {}")
    got = _resolve_task_dir(config, "tasks/smoke")
    assert got == tmp_path / "tasks" / "smoke"
