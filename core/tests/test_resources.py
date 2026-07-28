"""acquire/release discipline: idempotent, tolerant, always in the ledger."""

import subprocess

import pytest

from harness.config.schema import NeonCfg, RunSpec, Source
from harness.resources.base import Ledger, Resource, RunHandle, acquire_all, release_all
from harness.resources.worktree import Worktree, WorktreeError


def spec(**kw):
    return RunSpec(id=kw.get("id", "1"),
                   source=kw.get("source", Source(repo="x", ref="a" * 40)),
                   task="tasks/t", model="haiku", timeout_s=60,
                   neon=NeonCfg(project="p"), artifacts="artifacts")


def handle(**kw):
    return RunHandle(fanout="f-0728", spec=spec(**kw))


# -- ledger -------------------------------------------------------------------

def test_ledger_never_stores_secrets(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.record("neon-branch", "acquire", "ok",
               {"branch_id": "br-1", "secret_database_url": "postgres://creds"})
    text = (tmp_path / "ledger.jsonl").read_text()
    assert "br-1" in text and "creds" not in text


def test_unreleased_reads_the_ledger(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    led.record("neon-branch", "acquire", "ok")
    led.record("worktree", "acquire", "ok")
    led.record("worktree", "release", "ok")
    assert led.unreleased() == ["neon-branch"]  # the leak, by name


class Boom(Resource):
    kind = "boom"

    def acquire(self, run):
        raise RuntimeError("nope")

    def release(self, run):
        raise RuntimeError("release also broken")


class Ok(Resource):
    kind = "ok"
    released = 0

    def acquire(self, run):
        return {"got": "it"}

    def release(self, run):
        self.released += 1


def test_failed_acquire_rolls_back_what_was_held(tmp_path):
    ok, led = Ok(), Ledger(tmp_path / "l.jsonl")
    with pytest.raises(RuntimeError):
        acquire_all([ok, Boom()], handle(), led)
    assert ok.released == 1  # the one already held was given back
    verbs = [(e["kind"], e["verb"], e["status"]) for e in led.entries()]
    assert ("boom", "acquire", "failed") in verbs


def test_release_all_reports_instead_of_raising(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    failed = release_all([Boom(), Ok()], handle(), led)
    assert failed == ["boom"]  # broken teardown didn't stop the rest


# -- worktree, against real git -----------------------------------------------

@pytest.fixture
def source_repo(tmp_path):
    repo = tmp_path / "origin"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "hello.txt").write_text("one\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "one"], cwd=repo, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                         capture_output=True, text=True).stdout.strip()
    return repo, sha


def test_worktree_materializes_at_the_pinned_sha(tmp_path, source_repo):
    repo, sha = source_repo
    tree = Worktree(tmp_path / "wt")
    h = handle(source=Source(repo=str(repo), ref=sha))
    facts = tree.acquire(h)
    assert (tmp_path / "wt").as_posix() in facts["workdir"]
    assert facts["ref"] == sha
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=facts["workdir"],
                          capture_output=True, text=True).stdout.strip()
    assert head == sha


def test_worktree_reacquire_converges(tmp_path, source_repo):
    repo, sha = source_repo
    tree = Worktree(tmp_path / "wt")
    h = handle(source=Source(repo=str(repo), ref=sha))
    first = tree.acquire(h)["workdir"]
    assert tree.acquire(h)["workdir"] == first  # same run, same checkout


def test_worktree_refuses_a_dir_at_the_wrong_sha(tmp_path, source_repo):
    repo, sha = source_repo
    tree = Worktree(tmp_path / "wt")
    h = handle(source=Source(repo=str(repo), ref=sha))
    workdir = tree.acquire(h)["workdir"]
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "drift", "--allow-empty"],
                   cwd=workdir, check=True)
    h2 = handle(source=Source(repo=str(repo), ref=sha))
    h2.facts = {}
    with pytest.raises(WorktreeError, match="exists at"):
        tree.acquire(h2)


def test_worktree_release_twice_is_fine(tmp_path, source_repo):
    repo, sha = source_repo
    tree = Worktree(tmp_path / "wt")
    h = handle(source=Source(repo=str(repo), ref=sha))
    workdir = tree.acquire(h)["workdir"]
    tree.release(h)
    tree.release(h)  # second release: nothing to do, nothing to raise
    import os
    assert not os.path.exists(workdir)
