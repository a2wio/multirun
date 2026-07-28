"""The Neon resource against a fake transport — the real api is for the
smoke run, not the test suite."""

import io
import json
import urllib.error

import pytest

from harness.config.schema import NeonCfg, RunSpec, Source
from harness.resources.base import RunHandle
from harness.resources.neon import PARENT_PREFIX, NeonAPI, NeonBranch, sweep


class FakeNeon:
    """Answers like api.neon.tech would; records what it was asked."""

    def __init__(self):
        self.branches = [{"id": "br-main", "name": "main", "default": True,
                          "created_at": "2026-01-01T00:00:00Z"}]
        self.calls = []
        self.next_id = 0

    def __call__(self, req, timeout=None):
        method, path = req.get_method(), req.selector.split("/api/v2")[1]
        self.calls.append((method, path))
        body = json.loads(req.data) if req.data else None
        if method == "GET" and path.endswith("/branches"):
            return _resp({"branches": self.branches})
        if method == "POST" and path.endswith("/branches"):
            self.next_id += 1
            branch = {"id": f"br-{self.next_id}", **body["branch"],
                      "created_at": "2026-01-01T00:00:00Z"}
            self.branches.append(branch)
            return _resp({"branch": branch, "operations": []})
        if method == "DELETE":
            bid = path.rsplit("/", 1)[1]
            found = [b for b in self.branches if b["id"] == bid]
            if not found:
                raise urllib.error.HTTPError(path, 404, "no such branch", {},
                                             io.BytesIO(b"not found"))
            self.branches.remove(found[0])
            return _resp({"operations": []})
        if "connection_uri" in path:
            return _resp({"uri": "postgres://user:secret@host/db"})
        raise AssertionError(f"unexpected call {method} {path}")


def _resp(payload):
    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode()
    return R()


@pytest.fixture
def api():
    fake = FakeNeon()
    return NeonAPI(api_key="test-key", opener=fake), fake


def handle(run_id="1"):
    return RunHandle(fanout="smoke-0728", spec=RunSpec(
        id=run_id, source=Source(repo="x", ref="a" * 40), task="tasks/smoke",
        model="haiku", timeout_s=60, neon=NeonCfg(project="proj"),
        artifacts="artifacts"))


def test_acquire_creates_branch_and_returns_secret_uri(api):
    napi, fake = api
    facts = NeonBranch(napi, parent_id="br-main").acquire(handle())
    assert facts["branch_name"] == "mr-run-smoke-0728-1"
    assert facts["secret_database_url"].startswith("postgres://")
    assert any(b["name"] == "mr-run-smoke-0728-1" for b in fake.branches)


def test_acquire_twice_reuses_not_duplicates(api):
    napi, fake = api
    res = NeonBranch(napi, parent_id="br-main")
    first = res.acquire(handle())
    second = res.acquire(handle())
    assert first["branch_id"] == second["branch_id"]
    assert len([b for b in fake.branches if b["name"].startswith("mr-run")]) == 1


def test_release_deletes_and_release_again_is_silent(api):
    napi, fake = api
    res = NeonBranch(napi, parent_id="br-main")
    h = handle()
    h.facts.update(res.acquire(h))
    res.release(h)
    assert not any(b["name"].startswith("mr-run") for b in fake.branches)
    res.release(h)  # branch already gone: 404 swallowed by contract
    h2 = handle()   # release without ever acquiring: looks up, finds nothing
    res.release(h2)


def test_delete_branch_reports_already_gone(api):
    napi, _ = api
    assert napi.delete_branch("proj", "br-nope") is False


def test_resolve_parent_none_means_default(api):
    napi, _ = api
    assert napi.resolve_parent("proj", None)["id"] == "br-main"
    with pytest.raises(Exception, match="no branch"):
        napi.resolve_parent("proj", "ghost")


def test_sweep_reaps_only_orphaned_run_branches(api):
    napi, fake = api
    fake.branches += [
        {"id": "br-x", "name": "mr-run-old-1", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "br-y", "name": "mr-run-live-1", "created_at": "2026-01-01T00:00:00Z"},
        {"id": "br-z", "name": PARENT_PREFIX + "smoke",
         "created_at": "2026-01-01T00:00:00Z"},
    ]
    reaped = sweep(napi, "proj", active_slugs={"live-1"}, min_age_s=0)
    assert reaped == ["mr-run-old-1"]  # not the live run, never a parent
    assert any(b["name"] == PARENT_PREFIX + "smoke" for b in fake.branches)
