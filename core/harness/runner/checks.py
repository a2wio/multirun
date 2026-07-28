"""Did it work — the task's own checks, run after the agent stops.

A check is any executable or .sh file in the task's checks/ dir, run in
name order with the workdir as cwd and the run's env (DATABASE_URL
included). Exit 0 is a pass. Results land in checks.json; a run with
failing checks still produces all its artifacts — failing is a result,
not an error.
"""

import json
import subprocess
import time
from pathlib import Path

CHECK_TIMEOUT_S = 300


def discover(checks_dir: Path) -> list[Path]:
    if not checks_dir or not Path(checks_dir).is_dir():
        return []
    return sorted(p for p in Path(checks_dir).iterdir()
                  if p.is_file() and (p.suffix == ".sh" or p.stat().st_mode & 0o111))


def run_checks(checks_dir: Path, workdir: Path, env: dict,
               outdir: Path) -> dict:
    results = []
    for script in discover(checks_dir):
        started = time.monotonic()
        try:
            proc = subprocess.run(["bash", str(script)], cwd=str(workdir),
                                  env=env, capture_output=True, text=True,
                                  timeout=CHECK_TIMEOUT_S)
            rc, tail = proc.returncode, (proc.stdout + proc.stderr)[-2000:]
        except subprocess.TimeoutExpired:
            rc, tail = -1, f"timed out after {CHECK_TIMEOUT_S}s"
        results.append({"name": script.name, "pass": rc == 0, "exit": rc,
                        "seconds": round(time.monotonic() - started, 1),
                        "tail": tail})
    summary = {"total": len(results),
               "passed": sum(1 for r in results if r["pass"]),
               "checks": results}
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "checks.json").write_text(json.dumps(summary, indent=2) + "\n",
                                        encoding="utf-8")
    return summary
