"""The in-cluster loop: watch a mounted config dir, run what appears.

The controller Deployment mounts two things this module lives on: the
fanout ConfigMap at /etc/multirun (`fanout.yaml` + `stamp`, written by
`multirun publish`) and the subscription creds Secret at /creds/claude.
Each tick it

- keeps the creds fresh. A stale .credentials.json is a fleet-wide
  outage with a confusing face — every run failing auth at once — so
  freshness is checked every tick and during a fanout, refreshed via
  one no-op CLI turn, and the rotated file is pushed back into the
  Secret. Every outcome gets a loud log line; "why are runs failing"
  must be answerable from `kubectl logs` alone.
- picks up newly published fanouts. The publish stamp names the fanout
  instance deterministically, and the results db answers "was this
  instance already run" across controller restarts. Without a results
  db there is no cross-restart memory — the log says so at startup.

A fanout that crashed the controller mid-flight is NOT resumed: its
instance is already in the results db, so a restart skips it and the
reaper sweeps whatever it leaked. A failed fanout is a result too.
"""

import os
import time
import traceback
from pathlib import Path

import yaml

from ..config import ConfigError
from ..config.schema import FanoutConfig, parse_config
from ..results.db import Results
from . import controller as controller_mod
from . import plan as plan_mod
from . import reaper, spawn


def read_published(config_dir: Path) -> tuple[str, FanoutConfig] | None:
    """The mounted ConfigMap, parsed: (stamp, config), or None while
    nothing is published. Raises ConfigError on an invalid config —
    a published typo should be loud, not silently idle."""
    fanout_file = config_dir / "fanout.yaml"
    stamp_file = config_dir / "stamp"
    if not fanout_file.exists() or not stamp_file.exists():
        return None
    stamp = stamp_file.read_text(encoding="utf-8").strip()
    if not stamp:
        return None
    raw = yaml.safe_load(fanout_file.read_text(encoding="utf-8"))
    return stamp, parse_config(raw or {}, default_name="fanout")


def creds_tick(creds_dir: Path, *, namespace: str, secret: str, log) -> None:
    """Keep the mounted subscription creds usable, loudly."""
    src = Path(creds_dir) / ".credentials.json"
    if not src.exists():
        log(f"claude creds: {src} does not exist — `multirun creds push` "
            "from a logged-in machine; every run fails auth until then")
        return
    if not controller_mod.creds_stale(src.read_text(encoding="utf-8")):
        return
    log("claude creds: stale (expiring within the hour) — refreshing")
    try:
        rotated = controller_mod.refresh_creds(Path(creds_dir))
    except Exception as e:  # noqa: BLE001 — refresh failing must not kill the loop
        log(f"claude creds: refresh FAILED ({e}) — runs will fail auth; "
            "`multirun creds push` from a logged-in machine")
        return
    if rotated is None:
        log("claude creds: refresh turn ran but the file did not rotate — "
            "if runs fail auth, `multirun creds push` from a logged-in machine")
        return
    _patch_creds_secret(secret, namespace, rotated)
    log("claude creds: refreshed and pushed back into the Secret")


def _patch_creds_secret(name: str, namespace: str, credentials_json: str) -> None:
    from kubernetes import client, config
    config.load_incluster_config() if spawn._in_cluster() else config.load_kube_config()
    client.CoreV1Api().patch_namespaced_secret(
        name, namespace, {"stringData": {".credentials.json": credentials_json}})


def watch(config_dir: Path, *, runner_image: str, namespace: str = "multirun",
          creds_dir: Path = Path("/creds/claude"), creds_secret: str = "claude-creds",
          artifacts_root: Path | None = Path("/artifacts"),
          artifacts_claim: str | None = "multirun-artifacts",
          interval_s: int = 15, once: bool = False, log=print) -> None:
    results = Results.open(os.environ.get("RESULTS_DATABASE_URL"))
    if os.environ.get("RESULTS_DATABASE_URL") is None:
        log("no RESULTS_DATABASE_URL: no cross-restart memory — a restarted "
            "controller re-runs the mounted fanout")
    log(f"watching {config_dir} (runner={runner_image}, namespace={namespace})")
    seen: set[str] = set()
    while True:
        try:
            creds_tick(creds_dir, namespace=namespace, secret=creds_secret, log=log)
            published = read_published(Path(config_dir))
            if published:
                stamp, cfg = published
                instance = plan_mod.instance_name(cfg.name, stamp)
                if instance not in seen:
                    if results.fanout_exists(instance):
                        log(f"{instance}: already in the results db — skipping "
                            "(anything it leaked is the reaper's to sweep)")
                    else:
                        _run_fanout(cfg, stamp, instance, results=results,
                                    config_dir=Path(config_dir),
                                    runner_image=runner_image, namespace=namespace,
                                    creds_dir=creds_dir, creds_secret=creds_secret,
                                    artifacts_root=artifacts_root,
                                    artifacts_claim=artifacts_claim, log=log)
                    seen.add(instance)
        except ConfigError as e:
            log(f"published config is invalid: {e}")
        except Exception:  # noqa: BLE001 — the loop outlives its ticks
            log("watch tick failed:\n" + traceback.format_exc())
        if once:
            return
        time.sleep(interval_s)


def _run_fanout(cfg: FanoutConfig, stamp: str, instance: str, *, results,
                config_dir: Path, runner_image: str, namespace: str,
                creds_dir: Path, creds_secret: str,
                artifacts_root: Path | None, artifacts_claim: str | None,
                log) -> None:
    log(f"{instance}: picked up — {len(cfg.runs)} run(s), "
        f"max_parallel={cfg.max_parallel}")
    ctl = controller_mod.Controller(
        cfg, config_dir / "fanout.yaml", runner_image=runner_image,
        namespace=namespace, stamp=stamp,
        artifacts_root=artifacts_root, artifacts_claim=artifacts_claim)
    results.fanout(instance, cfg)
    # one transient api error must not abandon an hour of fan-out: log the
    # cycle's failure and try again. Launch and harvest are idempotent, so
    # a retried cycle converges instead of doubling anything.
    while True:
        try:
            if not ctl.reconcile():
                break
            reaper.reap(ctl)
            # a fanout outlasts a token lifetime; runs yet to spawn need it
            creds_tick(creds_dir, namespace=namespace, secret=creds_secret, log=log)
        except Exception:  # noqa: BLE001 — the fanout outlives its cycles
            log(f"{instance}: reconcile cycle failed, retrying:\n"
                + traceback.format_exc())
        time.sleep(10)
    log(f"{instance}: complete")
