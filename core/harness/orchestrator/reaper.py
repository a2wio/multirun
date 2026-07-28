"""Timeouts, crashes, teardown — the safety net under the ledger.

Two jobs:

- overdue runs: a Job that outlived timeout + grace gets deleted and
  its run marked failed(timeout). k8s's own activeDeadlineSeconds is
  the first line; the reaper is the second, and the one that also
  tears down the run's resources and writes the record.
- leaked branches: any mr-run-* branch in the project that no live run
  owns. Crashes leak; leaked branches bill monthly and nobody notices;
  the sweep unleaks. Old enough to be safely dead is an hour by
  default — a branch younger than that may belong to a run still
  provisioning.

The decisions are pure functions; the actions are thin.
"""

import time
from dataclasses import dataclass

from ..resources import neon


@dataclass(frozen=True)
class Overdue:
    job_name: str
    seconds_over: int


def overdue(started_at: float, timeout_s: int, grace_s: int = 600,
            now: float | None = None) -> int:
    """Seconds past the run's allowance; <= 0 means still within it."""
    return int((now if now is not None else time.time())
               - started_at - timeout_s - grace_s)


def find_overdue(active: dict[str, tuple[float, int]],
                 grace_s: int = 600, now: float | None = None) -> list[Overdue]:
    """active: job_name -> (started_at, timeout_s)."""
    out = []
    for job_name, (started_at, timeout_s) in active.items():
        over = overdue(started_at, timeout_s, grace_s, now)
        if over > 0:
            out.append(Overdue(job_name=job_name, seconds_over=over))
    return sorted(out, key=lambda o: -o.seconds_over)


def sweep_branches(project: str, active_slugs: set[str],
                   min_age_s: int = 3600) -> list[str]:
    """Delete every mr-run-* branch no live run owns. Returns names."""
    return neon.sweep(neon.NeonAPI(), project, active_slugs, min_age_s)


def reap(controller, grace_s: int = 600) -> list[str]:
    """One pass over a Controller's active runs. Returns reaped jobs."""
    from . import spawn
    reaped = []
    started = getattr(controller, "started", {})  # job_name -> started_at
    active = {name: (started.get(name, time.time()), p.spec.timeout_s)
              for name, p in controller.active.items()}
    for o in find_overdue(active, grace_s):
        p = controller.active[o.job_name]
        spawn.delete_job(o.job_name, controller.namespace)
        controller._harvest(p, "failed")
        del controller.active[o.job_name]
        reaped.append(o.job_name)
    return reaped
