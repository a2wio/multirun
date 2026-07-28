"""A checkout per run.

One bare mirror per source repo (fetched, never checked out), one git
worktree per run off that mirror, detached at the pinned sha. The sha
is the whole contract: every run of a fan-out starts from the same
commit or the comparison means nothing.

Also runnable as a module: in-cluster, an init container calls
`python -m harness.resources.worktree /config/run.yaml /work` to
materialize the checkout before the runner container starts — the
runner itself acquires nothing.
"""

import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

from .base import Resource, RunHandle


class WorktreeError(Exception):
    pass


def _git(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, timeout=600)
    if proc.returncode != 0:
        raise WorktreeError(f"git {' '.join(args[:3])}… failed: "
                            f"{proc.stderr.strip()[:500]}")
    return proc.stdout.strip()


def _mirror_path(root: Path, repo: str) -> Path:
    slug = repo.rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]
    return root / "mirrors" / f"{slug}-{sha256(repo.encode()).hexdigest()[:8]}.git"


def materialize(root: Path, repo: str, ref: str, workdir: Path) -> Path:
    """Mirror (or refresh) the repo, then hang a detached worktree at ref."""
    # git -C <mirror> resolves relative paths against the mirror — absolutize
    root, workdir = Path(root).resolve(), Path(workdir).resolve()
    mirror = _mirror_path(root, repo)
    if not mirror.exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--mirror", repo, str(mirror))
    if not _has_commit(mirror, ref):
        _git("fetch", "--prune", "origin", cwd=mirror)
    if not _has_commit(mirror, ref):
        raise WorktreeError(f"{ref} not found in {repo} even after fetch")
    if workdir.exists():  # idempotent re-acquire: reuse if it's the same ref
        head = _git("rev-parse", "HEAD", cwd=workdir)
        if head.startswith(ref) or ref.startswith(head[:len(ref)]):
            return workdir
        raise WorktreeError(f"{workdir} exists at {head[:12]}, wanted {ref}")
    workdir.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "--detach", str(workdir), ref, cwd=mirror)
    return workdir


def _has_commit(mirror: Path, ref: str) -> bool:
    proc = subprocess.run(["git", "cat-file", "-e", f"{ref}^{{commit}}"],
                          cwd=mirror, capture_output=True, timeout=60)
    return proc.returncode == 0


def remove(root: Path, repo: str, workdir: Path) -> None:
    """Drop the worktree; keep the mirror (it serves the next fan-out)."""
    root, workdir = Path(root).resolve(), Path(workdir).resolve()
    mirror = _mirror_path(root, repo)
    if mirror.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(workdir)],
                       cwd=mirror, capture_output=True, timeout=120)
        subprocess.run(["git", "worktree", "prune"], cwd=mirror,
                       capture_output=True, timeout=60)
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)


class Worktree(Resource):
    kind = "worktree"

    def __init__(self, root: Path):
        self.root = Path(root)

    def workdir_for(self, run: RunHandle) -> Path:
        return self.root / "work" / run.fanout / str(run.spec.id)

    def acquire(self, run: RunHandle) -> dict:
        src = run.spec.source
        workdir = materialize(self.root, src.repo, src.ref, self.workdir_for(run))
        return {"workdir": str(workdir), "ref": src.ref}

    def release(self, run: RunHandle) -> None:
        remove(self.root, run.spec.source.repo,
               Path(run.facts.get("workdir") or self.workdir_for(run)))


def main() -> None:
    """Init-container entrypoint: materialize from a rendered run config."""
    import yaml
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m harness.resources.worktree "
                         "<run.yaml> <root>")
    cfg = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8"))
    src, root = cfg["source"], Path(sys.argv[2])
    workdir = materialize(root, src["repo"], src["ref"], root / "checkout")
    print(workdir)


if __name__ == "__main__":
    main()
