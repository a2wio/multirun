"""The runner's non-agent parts: capture, checks, reaper math."""

import subprocess

from harness.orchestrator.reaper import find_overdue, overdue
from harness.runner import capture, checks


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "a.txt").write_text("original\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "base"], cwd=repo, check=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                         capture_output=True, text=True).stdout.strip()
    return repo, sha


def test_git_capture_sees_edits_and_untracked(tmp_path):
    repo, sha = _repo(tmp_path)
    (repo / "a.txt").write_text("changed\n")
    (repo / "NEW.md").write_text("the agent made this\n")
    out = tmp_path / "artifacts"
    got = capture.git_artifacts(repo, sha, out)
    patch = (out / "diff.patch").read_text()
    assert got["files_changed"] == 2
    assert "NEW.md" in patch and "changed" in patch


def test_git_capture_clean_tree_is_empty_not_an_error(tmp_path):
    repo, sha = _repo(tmp_path)
    got = capture.git_artifacts(repo, sha, tmp_path / "artifacts")
    assert got["files_changed"] == 0 and got["dirty"] is False


def test_checks_pass_fail_and_land_in_json(tmp_path):
    checks_dir, workdir = tmp_path / "checks", tmp_path / "wd"
    checks_dir.mkdir()
    workdir.mkdir()
    (checks_dir / "01-yes.sh").write_text("exit 0\n")
    (checks_dir / "02-no.sh").write_text("echo broken >&2; exit 3\n")
    summary = checks.run_checks(checks_dir, workdir, {"PATH": "/usr/bin:/bin"},
                                tmp_path / "art")
    assert (summary["total"], summary["passed"]) == (2, 1)
    failed = summary["checks"][1]
    assert failed["exit"] == 3 and "broken" in failed["tail"]
    assert (tmp_path / "art" / "checks.json").exists()


def test_no_checks_dir_means_zero_not_crash(tmp_path):
    summary = checks.run_checks(None, tmp_path, {}, tmp_path / "art")
    assert summary["total"] == 0


def test_overdue_math():
    assert overdue(started_at=0, timeout_s=600, grace_s=60, now=700) == 40
    assert overdue(started_at=0, timeout_s=600, grace_s=60, now=600) < 0


def test_find_overdue_sorts_worst_first():
    active = {"job-a": (0.0, 600), "job-b": (0.0, 60)}
    got = find_overdue(active, grace_s=0, now=700.0)
    assert [o.job_name for o in got] == ["job-b", "job-a"]
    assert got[0].seconds_over == 640
