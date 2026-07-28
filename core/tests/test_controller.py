"""Controller helpers that must be right before the cluster exists."""

import json
import time

from harness.config.schema import parse_config
from harness.orchestrator import controller as controller_mod
from harness.orchestrator import plan as plan_mod
from harness.orchestrator import spawn
from harness.orchestrator.controller import _resolve_task_dir, creds_stale
from harness.results.db import NullResults


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


def test_harvest_tears_down_the_runs_configmap_and_secret(monkeypatch):
    """The Job used to be the only thing deleted at harvest; the per-run
    ConfigMap and Secret piled up by the fanout-load."""
    deleted = []
    monkeypatch.setattr(spawn, "delete_job",
                        lambda name, ns: deleted.append(name))
    monkeypatch.setattr(spawn, "delete_configmap",
                        lambda name, ns: deleted.append(name))
    monkeypatch.setattr(spawn, "delete_secret",
                        lambda name, ns: deleted.append(name))

    class FakeBranch:
        def __init__(self, api=None, parent_id=None):
            pass

        def release(self, handle):
            pass

    monkeypatch.setattr(controller_mod.neon, "NeonBranch", FakeBranch)

    cfg = parse_config({
        "global": {"name": "bench", "task": "tasks/smoke", "model": "haiku",
                   "source": {"repo": "https://x/y.git", "ref": "a" * 40},
                   "neon": {"project": "proj"}},
        "runs": [{"id": "1"}],
    })
    p = plan_mod.plan(cfg, stamp="0728")[0]
    ctl = controller_mod.Controller.__new__(controller_mod.Controller)
    ctl.namespace = "multirun"
    ctl.results = NullResults()
    ctl.artifacts_root = None
    ctl.branch_facts = {}
    ctl.api = None
    ctl._harvest(p, "succeeded")
    assert deleted == [p.job_name, p.configmap_name, p.secret_name]


def test_task_dir_resolves_relative_to_the_config(tmp_path):
    (tmp_path / "tasks" / "smoke").mkdir(parents=True)
    (tmp_path / "tasks" / "smoke" / "task.md").write_text("do it")
    (tmp_path / "core" / "configs").mkdir(parents=True)
    config = tmp_path / "core" / "configs" / "smoke.yaml"
    config.write_text("global: {}")
    got = _resolve_task_dir(config, "tasks/smoke")
    assert got == tmp_path / "tasks" / "smoke"
