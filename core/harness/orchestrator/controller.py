"""Drives runs through their states.

    PENDING -> PROVISIONING -> SPAWNED -> RUNNING -> DIFFING
            -> TEARDOWN -> DONE | FAILED

Two callers share the machinery here:

- run_local(): ONE run end to end on this machine — worktree + Neon
  branch + agent + capture + db diff + teardown, no cluster anywhere.
  This is the provable loop, and the reference for what the cluster
  path must feel like.
- Controller: the in-cluster loop — provision, spawn a Job, poll,
  diff, tear down, record. Written to the same states, but it has not
  run against a real cluster yet (that's the deploy phase, out of
  scope here); treat it as the shape, not as proven.

Teardown is a state, not a finally block: it runs on success, failure
and timeout alike, and its outcome lands in the ledger and the results
db either way.

Credential freshness lives here too, because stale subscription creds
are a fleet-wide outage with a confusing face (every run failing auth).
The freshness check is pure; the refresh exercises the claude CLI on a
writable copy of the creds (one cheap no-op turn — the CLI does its own
oauth refresh) and pushes the rotated file back into the Secret.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..config.schema import FanoutConfig, RunSpec
from ..resources import neon
from ..resources.base import Ledger, RunHandle, acquire_all, release_all
from ..resources.storage import ArtifactDir
from ..resources.worktree import Worktree
from ..results.db import Results
from ..results.models import RunState
from ..runner import capture, entrypoint
from . import plan as plan_mod
from . import spawn


def _resolve_task_dir(config_path: Path, task: str) -> Path:
    """Task paths are relative to the repo root; walk up from the
    config first (its repo owns its tasks), fall back to the cwd so
    `multirun local core/configs/x.yaml` works from anywhere inside
    the checkout."""
    base = config_path.resolve().parent
    for root in (base, base.parent, base.parent.parent, Path.cwd()):
        if (root / task / "task.md").exists():
            return root / task
    raise FileNotFoundError(f"can't find {task}/task.md near {config_path}")


def _seed_files(task_dir: Path, seed: str | None) -> list[Path]:
    seed_dir = task_dir / (seed or "seed")
    return sorted(seed_dir.glob("*.sql")) if seed_dir.is_dir() else []


def run_local(config_path: Path, cfg: FanoutConfig, run_id: str | None = None,
              keep: bool = False, work_root: Path | None = None) -> dict:
    """One run, this machine, whole loop. Returns a result summary."""
    spec = _pick(cfg, run_id)
    p = plan_mod.RunPlan(fanout=plan_mod.instance_name(cfg.name), spec=spec)
    task_dir = _resolve_task_dir(config_path, spec.task)
    results = Results.open(os.environ.get("RESULTS_DATABASE_URL"))
    results.fanout(p.fanout, cfg)
    results.state(p.fanout, spec.id, RunState.PROVISIONING)

    handle = RunHandle(fanout=p.fanout, spec=spec)
    art = ArtifactDir()
    artifact_dir = Path(art.acquire(handle)["artifact_dir"])
    handle.facts["artifact_dir"] = str(artifact_dir)
    ledger = Ledger(artifact_dir / "ledger.jsonl")
    ledger.record(art.kind, "acquire", "ok", {"artifact_dir": str(artifact_dir)})

    api = neon.NeonAPI()
    parent = neon.ensure_seeded_parent(
        api, spec.neon.project, spec.neon.parent_branch, task_dir.name,
        _seed_files(task_dir, spec.source.seed),
        spec.neon.database, spec.neon.role)

    branch = neon.NeonBranch(api, parent_id=parent["id"])
    tree = Worktree(work_root or Path(".multirun-work"))
    acquired = [tree, branch]
    acquire_all(acquired, handle, ledger)
    for res in acquired:
        results.resource(p.fanout, spec.id, res.kind, "acquired")

    summary: dict = {"fanout": p.fanout, "run": spec.id,
                     "artifact_dir": str(artifact_dir),
                     "branch": handle.facts.get("branch_name")}
    try:
        run_yaml = artifact_dir / "run.yaml"
        run_yaml.write_text(spawn.build_run_yaml(
            p, task_name=task_dir.name,
            workdir=handle.facts["workdir"],
            artifact_dir=str(artifact_dir)), encoding="utf-8")
        # point the runner at the real task files instead of /config
        _patch_local_paths(run_yaml, task_dir)

        results.state(p.fanout, spec.id, RunState.RUNNING)
        rc = entrypoint.run(run_yaml, extra_env={
            "DATABASE_URL": handle.facts["secret_database_url"]})
        summary["runner_exit"] = rc

        results.state(p.fanout, spec.id, RunState.DIFFING)
        parent_uri = api.connection_uri(spec.neon.project, parent["id"],
                                        spec.neon.database, spec.neon.role)
        summary["db"] = capture.db_diff(
            parent_uri, handle.facts["secret_database_url"], artifact_dir)
    finally:
        results.state(p.fanout, spec.id, RunState.TEARDOWN)
        if keep:
            ledger.record("teardown", "release", "skipped", {"reason": "--keep"})
            summary["kept"] = True
        else:
            failed = release_all(list(reversed(acquired)), handle, ledger)
            for res in acquired:
                results.resource(p.fanout, spec.id, res.kind,
                                 "leaked" if res.kind in failed else "released")
            summary["leaked"] = failed
            summary["branch_gone"] = api.find_branch(
                spec.neon.project, p.branch_name) is None

    ok = summary.get("runner_exit") == 0 and not summary.get("leaked")
    results.state(p.fanout, spec.id, RunState.DONE if ok else RunState.FAILED)
    summary["state"] = "done" if ok else "failed"
    meta = artifact_dir / "meta.json"
    if meta.exists():
        results.finish(p.fanout, spec.id, json.loads(meta.read_text()))
    return summary


def _pick(cfg: FanoutConfig, run_id: str | None) -> RunSpec:
    if run_id is None:
        return cfg.runs[0]
    for spec in cfg.runs:
        if spec.id == str(run_id):
            return spec
    raise SystemExit(f"no run {run_id!r} in config (have: "
                     f"{', '.join(s.id for s in cfg.runs)})")


def _patch_local_paths(run_yaml: Path, task_dir: Path) -> None:
    import yaml
    cfg = yaml.safe_load(run_yaml.read_text(encoding="utf-8"))
    cfg["task"]["prompt_file"] = str(task_dir / "task.md")
    checks = task_dir / "checks"
    cfg["task"]["checks_dir"] = str(checks) if checks.is_dir() else None
    run_yaml.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


# -- the in-cluster loop (written to shape; unproven until deploy) ------------

class Controller:
    def __init__(self, cfg: FanoutConfig, config_path: Path, *,
                 runner_image: str, namespace: str = "multirun",
                 stamp: str | None = None,
                 artifacts_root: Path | None = None,
                 artifacts_claim: str | None = None):
        self.cfg = cfg
        self.plans = plan_mod.plan(cfg, stamp)
        self.task_dir = _resolve_task_dir(config_path, cfg.runs[0].task)
        self.runner_image = runner_image
        self.namespace = namespace
        # artifacts_root is where the shared volume is mounted HERE (and in
        # the run pods); artifacts_claim is the PVC the run pods mount. Both
        # unset = phase-1 behavior: emptyDir, artifacts die with the pod.
        self.artifacts_root = Path(artifacts_root) if artifacts_root else None
        self.artifacts_claim = artifacts_claim
        self.api = neon.NeonAPI()
        self.results = Results.open(os.environ.get("RESULTS_DATABASE_URL"))
        self.active: dict[str, plan_mod.RunPlan] = {}
        self.started: dict[str, float] = {}  # job_name -> when; the reaper's clock
        self.queue = list(self.plans)
        self.branch_facts: dict[str, dict] = {}

    def _artifact_dir(self, p: plan_mod.RunPlan) -> Path | None:
        if self.artifacts_root is None:
            return None
        return self.artifacts_root / p.fanout / str(p.spec.id)

    def reconcile(self) -> bool:
        """One pass: spawn up to max_parallel, harvest finished runs.
        Returns True while there is still work in flight."""
        while self.queue and len(self.active) < self.cfg.max_parallel:
            self._launch(self.queue.pop(0))
        for job_name, p in list(self.active.items()):
            status = spawn.job_status(job_name, self.namespace)
            if status in ("succeeded", "failed", "gone"):
                self._harvest(p, status)
                del self.active[job_name]
        return bool(self.queue or self.active)

    def _launch(self, p: plan_mod.RunPlan) -> None:
        spec = p.spec
        self.results.state(p.fanout, spec.id, RunState.PROVISIONING)
        parent = neon.ensure_seeded_parent(
            self.api, spec.neon.project, spec.neon.parent_branch,
            self.task_dir.name, _seed_files(self.task_dir, spec.source.seed),
            spec.neon.database, spec.neon.role)
        handle = RunHandle(fanout=p.fanout, spec=spec)
        facts = neon.NeonBranch(self.api, parent_id=parent["id"]).acquire(handle)
        self.branch_facts[p.slug] = {**facts, "parent_id": parent["id"]}
        self.results.resource(p.fanout, spec.id, "neon-branch", "acquired")

        checks = {f.name: f.read_text(encoding="utf-8")
                  for f in sorted((self.task_dir / "checks").glob("*"))
                  if f.is_file()} if (self.task_dir / "checks").is_dir() else {}
        art_dir = self._artifact_dir(p)
        manifests = [
            spawn.build_configmap(p, task_name=self.task_dir.name,
                                  task_md=(self.task_dir / "task.md").read_text(),
                                  checks=checks, namespace=self.namespace,
                                  artifact_dir=str(art_dir) if art_dir else None),
            spawn.build_secret(p, database_url=facts["secret_database_url"],
                               namespace=self.namespace),
            spawn.build_job(p, runner_image=self.runner_image,
                            check_names=sorted(checks),
                            namespace=self.namespace,
                            artifacts_claim=self.artifacts_claim),
        ]
        spawn.apply(manifests, self.namespace)
        self.results.state(p.fanout, spec.id, RunState.RUNNING)
        self.started[p.job_name] = time.time()
        self.active[p.job_name] = p

    def _harvest(self, p: plan_mod.RunPlan, status: str) -> None:
        spec, facts = p.spec, self.branch_facts.get(p.slug, {})
        self.results.state(p.fanout, spec.id, RunState.DIFFING)
        # db diff before teardown — it needs the branch alive. The diffs land
        # next to the runner's own artifacts on the shared volume, so one
        # directory answers for the whole run.
        art_dir = self._artifact_dir(p)
        outdir = art_dir if art_dir else Path(tempfile.mkdtemp(prefix=f"mr-{p.slug}-"))
        try:
            if facts.get("parent_id"):
                parent_uri = self.api.connection_uri(
                    spec.neon.project, facts["parent_id"],
                    spec.neon.database, spec.neon.role)
                capture.db_diff(parent_uri, facts["secret_database_url"], outdir)
        finally:
            self.results.state(p.fanout, spec.id, RunState.TEARDOWN)
            handle = RunHandle(fanout=p.fanout, spec=spec, facts=facts)
            neon.NeonBranch(self.api).release(handle)
            self.results.resource(p.fanout, spec.id, "neon-branch", "released")
            spawn.delete_job(p.job_name, self.namespace)
        meta_file = art_dir / "meta.json" if art_dir else None
        if meta_file and meta_file.exists():
            self.results.finish(p.fanout, spec.id, json.loads(
                meta_file.read_text(encoding="utf-8")))
        final = RunState.DONE if status == "succeeded" else RunState.FAILED
        self.results.state(p.fanout, spec.id, final)


# -- credential freshness -----------------------------------------------------

def creds_stale(credentials_json: str, horizon_s: int = 300) -> bool:
    """True when the oauth access token is expired or about to be.

    Access tokens are minted with under an hour on the clock, so any
    horizon near an hour is true on every tick — the horizon is only
    slack for a refresh to land before the token actually dies. What
    keeps runs authenticating is the refresh token; this predicate just
    picks the moment to exercise it. Pure: feed it the mounted Secret's
    .credentials.json content."""
    try:
        expires_ms = json.loads(credentials_json)["claudeAiOauth"]["expiresAt"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return True  # unreadable creds are stale creds
    return (expires_ms / 1000 - time.time()) < horizon_s


def refresh_creds(creds_dir: Path) -> tuple[bool, str | None]:
    """Run one no-op CLI turn on a writable copy of the creds; the CLI
    refreshes its own token. Returns (turn_ok, rotated): the rotated
    file's content when it changed, for the caller to push back into
    the Secret — and whether the turn itself authenticated, because a
    turn that completes proves the refresh token works even when the
    CLI saw no reason to rewrite the file."""
    src = creds_dir / ".credentials.json"
    before = src.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="mr-creds-") as tmp:
        home = Path(tmp)
        (home / ".claude").mkdir()
        shutil.copy(src, home / ".claude" / ".credentials.json")
        proc = subprocess.run(["claude", "-p", "ok", "--model", "haiku"],
                              env={**os.environ, "HOME": str(home)},
                              capture_output=True, text=True, timeout=120)
        after = (home / ".claude" / ".credentials.json").read_text(encoding="utf-8")
    return proc.returncode == 0, (after if after != before else None)
