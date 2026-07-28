"""Every per-run resource sits behind the same two verbs.

A resource is anything a run needs that exists outside the run: a Neon
branch, a git worktree, an artifact prefix — later a k8s namespace, a
bucket, whatever. Adding one is one new file in this directory, not a
runner rewrite.

Rules of the house:
- acquire() is idempotent: called twice for the same run, it converges
  on the same resource instead of making a second one.
- release() is idempotent and tolerant: called twice, or called for a
  resource that never finished acquiring, it does nothing loudly.
- Both verbs write to the Ledger. Teardown is a first-class state with
  its own record, not a finally block — leaked branches bill monthly
  and nobody notices, so "did release actually run" must be answerable
  from the ledger months later.
- facts returned by acquire() may contain secrets (connection uris).
  The ledger never stores facts marked secret; they flow to the run's
  env and nowhere else.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config.schema import RunSpec

SECRET_PREFIX = "secret_"  # facts named secret_* stay out of the ledger


@dataclass
class RunHandle:
    """What resources know about the run they serve."""
    fanout: str
    spec: RunSpec
    facts: dict = field(default_factory=dict)  # merged facts from all acquires

    @property
    def slug(self) -> str:
        return f"{self.fanout}-{self.spec.id}"


class Resource:
    kind: str = "resource"

    def acquire(self, run: RunHandle) -> dict:
        raise NotImplementedError

    def release(self, run: RunHandle) -> None:
        raise NotImplementedError


class Ledger:
    """Append-only record of every acquire/release, one file per run.

    This file is an artifact: it survives the run and is the answer to
    "what did run 7 hold, and was it all given back?".
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, kind: str, verb: str, status: str, detail: dict | None = None):
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind,
                 "verb": verb, "status": status,
                 "detail": {k: v for k, v in (detail or {}).items()
                            if not k.startswith(SECRET_PREFIX)}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in
                self.path.read_text(encoding="utf-8").splitlines() if line]

    def unreleased(self) -> list[str]:
        """Kinds acquired but never successfully released."""
        held: dict[str, str] = {}
        for e in self.entries():
            if e["verb"] == "acquire" and e["status"] == "ok":
                held[e["kind"]] = "held"
            elif e["verb"] == "release" and e["status"] in ("ok", "absent"):
                held[e["kind"]] = "released"
        return [k for k, v in held.items() if v == "held"]


def acquire_all(resources: list[Resource], run: RunHandle, ledger: Ledger) -> None:
    """Acquire in order; on failure release what was already acquired."""
    done: list[Resource] = []
    for res in resources:
        try:
            facts = res.acquire(run) or {}
            run.facts.update(facts)
            ledger.record(res.kind, "acquire", "ok", facts)
            done.append(res)
        except Exception as e:
            ledger.record(res.kind, "acquire", "failed", {"error": str(e)})
            release_all(list(reversed(done)), run, ledger)
            raise


def release_all(resources: list[Resource], run: RunHandle, ledger: Ledger) -> list[str]:
    """Release in reverse-acquire order. Never raises: teardown reports,
    it doesn't abort halfway and leak the rest. Returns failed kinds."""
    failed = []
    for res in resources:
        try:
            res.release(run)
            ledger.record(res.kind, "release", "ok")
        except Exception as e:
            ledger.record(res.kind, "release", "failed", {"error": str(e)})
            failed.append(res.kind)
    return failed
