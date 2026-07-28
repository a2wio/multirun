"""Read /config/run.yaml, do the run, write artifacts. That's all.

The runner is deliberately dumb. It acquires nothing: the worktree is
already on disk (init container in-cluster, the CLI locally), the
database branch already exists and arrives as DATABASE_URL in the
environment. It never talks to the k8s api, never talks to the Neon
api, never imports orchestrator code. Config in, artifacts out is the
entire contract — that is what keeps a failed pod debuggable.

The rendered run.yaml the runner reads:

    fanout: smoke-2607
    run: "1"
    model: haiku
    timeout_s: 600
    source: {repo: ..., ref: ...}
    workdir: /work/checkout
    artifact_dir: /artifacts
    task:
      name: smoke
      prompt_file: /config/task.md
      checks_dir: /config/checks     # optional
    env: {}                          # optional, non-secret extras
    dotenv: /secrets/run.env         # optional, more env from a file
"""

import os
import sys
import time
from pathlib import Path

import yaml

from ..promptlib import load_file, prompts
from . import agent, capture, checks

prompt = prompts(__file__)


def _load_dotenv(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _log(artifact_dir: Path, line: str) -> None:
    stamped = f"{time.strftime('%H:%M:%S')} {line}"
    print(stamped, flush=True)
    with (artifact_dir / "run.log").open("a", encoding="utf-8") as f:
        f.write(stamped + "\n")


def run(config_path: Path, extra_env: dict | None = None) -> int:
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    workdir = Path(cfg["workdir"])
    artifact_dir = Path(cfg["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    if not workdir.is_dir():
        _log(artifact_dir, f"workdir {workdir} does not exist — the runner "
                           "acquires nothing; whoever spawned this run owed "
                           "it a checkout")
        return 2

    env = dict(cfg.get("env") or {})
    if cfg.get("dotenv"):
        env.update(_load_dotenv(Path(cfg["dotenv"])))
    env.update(extra_env or {})

    task = cfg["task"]
    task_md = load_file(Path(task["prompt_file"]),
                        run_id=cfg["run"], task_name=task["name"])
    full_prompt = "\n\n".join([
        prompt("task_preamble", run_id=cfg["run"], task_name=task["name"]),
        prompt("repo_brief", repo=cfg["source"]["repo"], ref=cfg["source"]["ref"]),
        task_md,
    ])

    _log(artifact_dir, f"run {cfg['run']} starting: task={task['name']} "
                       f"model={cfg['model']} timeout={cfg['timeout_s']}s")

    result = agent.run_task(full_prompt, workdir=workdir, model=cfg["model"],
                            timeout_s=int(cfg["timeout_s"]),
                            trace_path=artifact_dir / "trace.jsonl",
                            extra_env=env)
    _log(artifact_dir, f"agent {result.exit_reason}: {result.num_turns} turns, "
                       f"{result.duration_ms}ms")

    git = capture.git_artifacts(workdir, cfg["source"]["ref"], artifact_dir)
    _log(artifact_dir, f"tree captured: {git['files_changed']} file(s) changed")

    check_env = {**os.environ, **env}
    checks_dir = task.get("checks_dir")
    summary = checks.run_checks(Path(checks_dir) if checks_dir else None,
                                workdir, check_env, artifact_dir)
    if summary["total"]:
        _log(artifact_dir, f"checks: {summary['passed']}/{summary['total']} passed")

    capture.write_meta(artifact_dir, result, started_at=started,
                       extra={"fanout": cfg["fanout"], "run": cfg["run"],
                              "model": cfg["model"], "git": git,
                              "checks_passed": summary["passed"],
                              "checks_total": summary["total"]})
    return 1 if result.is_error else 0


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1
                else os.environ.get("RUN_CONFIG", "/config/run.yaml"))
    raise SystemExit(run(path))


if __name__ == "__main__":
    main()
