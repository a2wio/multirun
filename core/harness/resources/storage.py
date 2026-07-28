"""An artifact prefix per run.

Phase 1 artifacts are a local directory tree:

    <artifacts>/<fanout>/<run-id>/
        run.yaml        the exact merged config this run got
        trace.jsonl     every agent message, as it streamed
        diff.patch      what the agent did to the tree
        schema.diff     what it did to the database's shape
        data_diff.json  what it did to the rows
        checks.json     did it work
        meta.json       tokens, timing, exit reason
        ledger.jsonl    what was held, what was given back
        run.log         the runner's own account

release() deliberately does NOT delete: artifacts are the product of a
run, not a resource the run borrowed. They outlive teardown by design.
Swapping this for object storage later is this one file.
"""

from pathlib import Path

from .base import Resource, RunHandle


class ArtifactDir(Resource):
    kind = "artifacts"

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else None

    def path_for(self, run: RunHandle) -> Path:
        root = self.root or Path(run.spec.artifacts)
        return root / run.fanout / str(run.spec.id)

    def acquire(self, run: RunHandle) -> dict:
        path = self.path_for(run)
        path.mkdir(parents=True, exist_ok=True)
        return {"artifact_dir": str(path)}

    def release(self, run: RunHandle) -> None:
        pass  # artifacts outlive the run — see module docstring
