"""A Neon branch per run.

All N runs start from byte-identical database state because they all
branch off the same parent — copy-on-write, effectively free to make,
$1.50/month each to forget. So: create is idempotent (a re-run of the
same run reuses its branch), delete tolerates already-gone, and every
verb lands in the ledger.

Auth is NEON_API_KEY in the environment; the api surface here is the
few calls we need against api v2, stdlib only. Connection uris carry
live credentials: they travel as secret_* facts (env-only, never
ledger, never logs).

Seeded parents: a task with seed fixtures gets its own parent branch
(`mr-parent-<task>`) created once off the configured parent and seeded
via psql; runs branch off that. The diff of a run branch against its
parent is then exactly what the agent did — the seed lives upstream of
every run. Parents are kept between fan-outs (one cheap branch per
task); `multirun teardown --sweep` can reap them.
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC

from .base import Resource, RunHandle

API = "https://console.neon.tech/api/v2"
PARENT_PREFIX = "mr-parent-"
RUN_PREFIX = "mr-run-"


class NeonError(Exception):
    pass


class NeonAPI:
    def __init__(self, api_key: str | None = None, opener=None):
        self.api_key = api_key or os.environ.get("NEON_API_KEY", "")
        if not self.api_key:
            raise NeonError("NEON_API_KEY is not set")
        # test seam: anything with the signature of urlopen
        self._open = opener or urllib.request.urlopen

    def _call(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(
            API + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Accept": "application/json",
                     "Content-Type": "application/json",
                     "User-Agent": "multirun/0.1"})
        try:
            with self._open(req, timeout=60) as r:
                return json.loads(r.read() or "null")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise NeonError(f"{method} {path} -> {e.code}: {detail}") from None

    # -- the few calls we need ------------------------------------------------

    def list_branches(self, project: str) -> list[dict]:
        return self._call("GET", f"/projects/{project}/branches").get("branches", [])

    def find_branch(self, project: str, name: str) -> dict | None:
        return next((b for b in self.list_branches(project) if b["name"] == name), None)

    def default_branch(self, project: str) -> dict:
        for b in self.list_branches(project):
            if b.get("default"):
                return b
        raise NeonError(f"project {project} has no default branch?")

    def resolve_parent(self, project: str, parent: str | None) -> dict:
        """parent may be a branch id, a branch name, or None (default)."""
        if parent is None:
            return self.default_branch(project)
        for b in self.list_branches(project):
            if parent in (b["id"], b["name"]):
                return b
        raise NeonError(f"no branch {parent!r} in project {project}")

    def create_branch(self, project: str, parent_id: str, name: str) -> dict:
        got = self._call("POST", f"/projects/{project}/branches",
                         {"branch": {"parent_id": parent_id, "name": name},
                          "endpoints": [{"type": "read_write"}]})
        self._wait_operations(project, got.get("operations", []))
        return got["branch"]

    def delete_branch(self, project: str, branch_id: str) -> bool:
        """True if deleted, False if it was already gone."""
        try:
            got = self._call("DELETE", f"/projects/{project}/branches/{branch_id}")
        except NeonError as e:
            if "-> 404" in str(e):
                return False
            raise
        self._wait_operations(project, got.get("operations", []))
        return True

    def connection_uri(self, project: str, branch_id: str,
                       database: str, role: str) -> str:
        q = urllib.parse.urlencode({"branch_id": branch_id,
                                    "database_name": database, "role_name": role})
        return self._call("GET", f"/projects/{project}/connection_uri?{q}")["uri"]

    def _wait_operations(self, project: str, operations: list[dict],
                         timeout_s: int = 120) -> None:
        deadline = time.monotonic() + timeout_s
        for op in operations:
            while True:
                status = op.get("status")
                if status in ("finished", "skipped"):
                    break
                if status in ("failed", "error", "cancelled"):
                    raise NeonError(f"operation {op.get('id')} {status}")
                if time.monotonic() > deadline:
                    raise NeonError(f"operation {op.get('id')} still {status} "
                                    f"after {timeout_s}s")
                time.sleep(2)
                op = self._call("GET", f"/projects/{project}/operations/{op['id']}"
                                ).get("operation", op)


def run_sql_file(uri: str, sql_path, psql: str | None = None) -> None:
    """Apply a .sql file over a connection uri. psql does the work."""
    cmd = [psql or os.environ.get("PSQL", "psql"), uri,
           "-v", "ON_ERROR_STOP=1", "-q", "-f", str(sql_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise NeonError(f"seeding {sql_path} failed: {proc.stderr.strip()[:500]}")


def ensure_seeded_parent(api: NeonAPI, project: str, base_parent: str | None,
                         task_name: str, seed_files: list, database: str,
                         role: str) -> dict:
    """The per-task parent branch: created once, seeded once, then shared
    by every run of that task. Idempotent — an existing parent is reused
    as-is (fixtures are versioned files; changing them means a new task
    name or deleting the parent first)."""
    name = PARENT_PREFIX + task_name
    existing = api.find_branch(project, name)
    if existing:
        return existing
    base = api.resolve_parent(project, base_parent)
    branch = api.create_branch(project, base["id"], name)
    uri = api.connection_uri(project, branch["id"], database, role)
    for sql in seed_files:
        run_sql_file(uri, sql)
    return branch


class NeonBranch(Resource):
    """acquire(): branch off the parent, hand back a connection uri.
    release(): delete the branch. Both safe to repeat."""

    kind = "neon-branch"

    def __init__(self, api: NeonAPI | None = None, parent_id: str | None = None):
        self.api = api or NeonAPI()
        self.parent_id = parent_id  # resolved by the orchestrator; None = config

    def _resolve_parent_id(self, run: RunHandle) -> str:
        if self.parent_id:
            return self.parent_id
        neon = run.spec.neon
        return self.api.resolve_parent(neon.project, neon.parent_branch)["id"]

    def acquire(self, run: RunHandle) -> dict:
        neon = run.spec.neon
        name = RUN_PREFIX + run.slug
        branch = self.api.find_branch(neon.project, name)
        if branch is None:
            branch = self.api.create_branch(neon.project,
                                            self._resolve_parent_id(run), name)
        uri = self.api.connection_uri(neon.project, branch["id"],
                                      neon.database, neon.role)
        return {"branch_id": branch["id"], "branch_name": name,
                "parent_id": branch.get("parent_id"),
                "secret_database_url": uri}

    def release(self, run: RunHandle) -> None:
        neon = run.spec.neon
        branch_id = run.facts.get("branch_id")
        if not branch_id:
            found = self.api.find_branch(neon.project, RUN_PREFIX + run.slug)
            if found is None:
                return  # never created, or already gone — both fine
            branch_id = found["id"]
        self.api.delete_branch(neon.project, branch_id)


def sweep(api: NeonAPI, project: str, active_slugs: set[str],
          min_age_s: int = 3600) -> list[str]:
    """Delete mr-run-* branches that no live run owns. The safety net
    under the ledger: crashes leak, the sweeper unleaks."""
    reaped = []
    for b in api.list_branches(project):
        if not b["name"].startswith(RUN_PREFIX):
            continue
        if b["name"].removeprefix(RUN_PREFIX) in active_slugs:
            continue
        created = b.get("created_at", "")
        # branches younger than min_age_s may belong to a run still starting
        if created and _age_seconds(created) < min_age_s:
            continue
        api.delete_branch(project, b["id"])
        reaped.append(b["name"])
    return reaped


def _age_seconds(created_at: str) -> float:
    from datetime import datetime
    try:
        then = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (datetime.now(UTC) - then).total_seconds()
