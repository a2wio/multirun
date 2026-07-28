"""What a run leaves behind: git diff, db diff, trace, tokens, timing.

The trace streams from agent.py as the run happens; everything else is
gathered here after the agent stops. Git capture happens in the runner.
The db diff does not — it needs the parent branch's uri, which the
runner never holds — so db_diff() is called by whoever orchestrates
(the controller in-cluster, the CLI locally), before teardown deletes
the branch.
"""

import json
import subprocess
import time
from pathlib import Path

from .agent import AgentResult


def _git(workdir: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(workdir), *args],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def git_artifacts(workdir: Path, ref: str, outdir: Path) -> dict:
    """Everything the agent did to the tree, vs the pinned commit.

    Untracked files are staged first (gitignore still applies) so the
    patch is complete whether or not the agent committed its work.
    """
    outdir.mkdir(parents=True, exist_ok=True)
    status = _git(workdir, "status", "--porcelain")
    _git(workdir, "add", "-A")
    patch = _git(workdir, "diff", ref)
    stat = _git(workdir, "diff", "--stat", ref)
    (outdir / "diff.patch").write_text(patch, encoding="utf-8")
    (outdir / "diff.stat.txt").write_text(stat, encoding="utf-8")
    (outdir / "status.txt").write_text(status, encoding="utf-8")
    files_changed = len([line for line in patch.splitlines()
                         if line.startswith("diff --git ")])
    return {"files_changed": files_changed, "dirty": bool(status.strip())}


def write_meta(outdir: Path, result: AgentResult, *, started_at: float,
               extra: dict | None = None) -> dict:
    meta = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                    time.localtime(started_at)),
        "wall_seconds": round(time.time() - started_at, 1),
        "exit_reason": result.exit_reason,
        "is_error": result.is_error,
        "num_turns": result.num_turns,
        "agent_duration_ms": result.duration_ms,
        "session_id": result.session_id,
        "usage": result.usage,
        "total_cost_usd": result.total_cost_usd,
        **(extra or {}),
    }
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                      encoding="utf-8")
    return meta


def db_diff(parent_uri: str, branch_uri: str, outdir: Path) -> dict:
    """Branch vs parent: schema and rows. Orchestrator/CLI-side only."""
    from ..diff import data_diff, schema_diff
    outdir.mkdir(parents=True, exist_ok=True)
    schema = schema_diff.diff(parent_uri, branch_uri)
    (outdir / "schema.diff").write_text(schema.text, encoding="utf-8")
    data = data_diff.diff(parent_uri, branch_uri)
    (outdir / "data_diff.json").write_text(json.dumps(data, indent=2) + "\n",
                                           encoding="utf-8")
    return {"schema_changed": schema.changed,
            "tables_touched": [t for t, d in data.get("tables", {}).items()
                               if d.get("added") or d.get("removed")
                               or d.get("only_in") ]}
