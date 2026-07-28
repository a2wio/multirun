"""multirun — submit / status / logs / teardown, and the local loop.

`multirun local <config>` is the provable path: one run end to end on
this machine, no cluster. The cluster commands (submit, status, logs,
teardown --fanout) are written against the same plans and manifests but
haven't met a real cluster yet — deploy is its own phase.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml

from .config import ConfigError
from .config.schema import parse_config
from .orchestrator import controller, reaper, spawn
from .orchestrator import plan as plan_mod
from .results.db import Results


def load(path: str):
    """load_config, plus: a task's source.yaml supplies source when the
    config doesn't — the task names its source, the config may override."""
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"no such config: {p}") from None
    glob = (raw or {}).get("global") or {}
    if "source" not in glob and "task" in glob:
        task_dir = controller._resolve_task_dir(p, glob["task"])
        src_file = task_dir / "source.yaml"
        if src_file.exists():
            glob["source"] = yaml.safe_load(src_file.read_text(encoding="utf-8"))
            raw["global"] = glob
    try:
        return parse_config(raw, default_name=p.stem)
    except ConfigError as e:
        raise SystemExit(f"config error: {e}") from None


def cmd_validate(args) -> None:
    cfg = load(args.config)
    print(f"ok: {len(cfg.runs)} run(s), max_parallel={cfg.max_parallel}")


def cmd_plan(args) -> None:
    cfg = load(args.config)
    for p in plan_mod.plan(cfg, stamp=args.stamp):
        print(f"{p.spec.id:>4}  model={p.spec.model:<10} "
              f"branch={p.branch_name}  job={p.job_name}")


def cmd_local(args) -> None:
    cfg = load(args.config)
    summary = controller.run_local(Path(args.config), cfg, run_id=args.run,
                                   keep=args.keep)
    print(json.dumps(summary, indent=2))
    if summary.get("kept"):
        print(f"\nkept: branch {summary['branch']} is still alive and "
              "billing — tear it down yourself", file=sys.stderr)
    sys.exit(0 if summary["state"] == "done" else 1)


def cmd_submit(args) -> None:
    cfg = load(args.config)
    ctl = controller.Controller(cfg, Path(args.config),
                                runner_image=args.runner_image,
                                namespace=args.namespace,
                                artifacts_claim=args.artifacts_pvc or None)
    print(f"fanout {ctl.plans[0].fanout}: {len(ctl.plans)} run(s), "
          f"max_parallel={cfg.max_parallel}")
    import time
    while ctl.reconcile():
        reaper.reap(ctl)
        time.sleep(10)
    print("fanout complete")


def cmd_publish(args) -> None:
    """Render a fanout config into the controller's ConfigMap. The
    in-cluster watch loop picks it up within its interval; the stamp
    names the instance, so publishing the same config twice runs it
    twice — deliberately."""
    import time

    cfg = load(args.config)
    stamp = args.stamp or time.strftime("%m%d%H%M%S")
    instance = plan_mod.instance_name(cfg.name, stamp)
    body = {"metadata": {"name": args.configmap},
            "data": {"fanout.yaml": yaml.safe_dump(cfg.raw, sort_keys=False),
                     "stamp": stamp}}
    from kubernetes import client, config
    config.load_kube_config()
    api = client.CoreV1Api()
    try:
        api.patch_namespaced_config_map(args.configmap, args.namespace, body)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise
        api.create_namespaced_config_map(
            args.namespace, {**body, "apiVersion": "v1", "kind": "ConfigMap"})
    print(f"published {instance}: {len(cfg.runs)} run(s), "
          f"max_parallel={cfg.max_parallel} -> configmap {args.configmap}")


def cmd_watch(args) -> None:
    from pathlib import Path as P

    from .orchestrator import watch as watch_mod
    watch_mod.watch(P(args.config_dir), runner_image=args.runner_image,
                    namespace=args.namespace, creds_dir=P(args.creds_dir),
                    creds_secret=args.creds_secret,
                    artifacts_root=P(args.artifacts_root),
                    artifacts_claim=args.artifacts_pvc,
                    interval_s=args.interval, once=args.once)


def cmd_status(args) -> None:
    from kubernetes import client, config
    config.load_kube_config()
    jobs = client.BatchV1Api().list_namespaced_job(
        args.namespace, label_selector="app=multirun")
    for job in jobs.items:
        s = job.status
        state = ("succeeded" if s.succeeded else
                 "failed" if s.failed else
                 "running" if s.active else "pending")
        labels = job.metadata.labels or {}
        print(f"{labels.get('multirun/fanout', '?'):<24} "
              f"run={labels.get('multirun/run', '?'):<6} {state}")


def cmd_logs(args) -> None:
    from kubernetes import client, config
    config.load_kube_config()
    core = client.CoreV1Api()
    pods = core.list_namespaced_pod(
        args.namespace, label_selector=f"multirun/fanout={args.fanout},"
                                       f"multirun/run={args.run}")
    for pod in pods.items:
        print(core.read_namespaced_pod_log(pod.metadata.name, args.namespace,
                                           container="runner", tail_lines=200))


def cmd_teardown(args) -> None:
    if args.sweep:
        reaped = reaper.sweep_branches(args.project, active_slugs=set(),
                                       min_age_s=args.min_age)
        print(f"reaped {len(reaped)} branch(es)"
              + (": " + ", ".join(reaped) if reaped else ""))
        return
    if not args.fanout:
        raise SystemExit("teardown needs --fanout or --sweep")
    from kubernetes import client, config
    config.load_kube_config()
    jobs = client.BatchV1Api().list_namespaced_job(
        args.namespace, label_selector=f"multirun/fanout={args.fanout}")
    for job in jobs.items:
        spawn.delete_job(job.metadata.name, args.namespace)
        print(f"deleted job {job.metadata.name}")
    reaped = reaper.sweep_branches(args.project, active_slugs=set(), min_age_s=0)
    print(f"reaped {len(reaped)} branch(es)")


def cmd_db_migrate(args) -> None:
    uri = os.environ.get("RESULTS_DATABASE_URL")
    if not uri:
        raise SystemExit("RESULTS_DATABASE_URL is not set")
    applied = Results.open(uri).migrate()
    print(f"applied: {', '.join(applied) if applied else 'nothing — up to date'}")


def cmd_creds_push(args) -> None:
    """Push the local subscription creds into the cluster Secret. Re-run
    whenever they rotate; the controller warns when they go stale."""
    creds = Path.home() / ".claude" / ".credentials.json"
    if not creds.exists():
        raise SystemExit(f"{creds} not found — log the claude CLI in first")
    if controller.creds_stale(creds.read_text(encoding="utf-8")):
        print("warning: these creds expire within the hour; refresh first "
              "(any `claude -p` turn does it)", file=sys.stderr)
    from kubernetes import client, config
    config.load_kube_config()
    body = {"metadata": {"name": args.secret},
            "stringData": {".credentials.json": creds.read_text(encoding="utf-8")}}
    api = client.CoreV1Api()
    try:
        api.patch_namespaced_secret(args.secret, args.namespace, body)
        print(f"updated secret {args.secret}")
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise
        api.create_namespaced_secret(args.namespace,
                                     {**body, "apiVersion": "v1",
                                      "kind": "Secret", "type": "Opaque"})
        print(f"created secret {args.secret}")


def main() -> None:
    top = argparse.ArgumentParser(prog="multirun")
    sub = top.add_subparsers(dest="command", required=True)

    def add(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.set_defaults(fn=fn)
        return p

    add("validate", cmd_validate).add_argument("config")
    p = add("plan", cmd_plan)
    p.add_argument("config")
    p.add_argument("--stamp", help="fix the fanout stamp (for reproducibility)")

    p = add("local", cmd_local, help="one run end to end on this machine")
    p.add_argument("config")
    p.add_argument("--run", help="run id (default: first)")
    p.add_argument("--keep", action="store_true",
                   help="skip teardown — the branch keeps billing")

    p = add("submit", cmd_submit, help="fan out on the cluster, driven from here")
    p.add_argument("config")
    p.add_argument("--runner-image", required=True)
    p.add_argument("--namespace", default="multirun")
    p.add_argument("--artifacts-pvc", default="multirun-artifacts",
                   help="PVC the run pods write artifacts to; '' for emptyDir")

    p = add("publish", cmd_publish,
            help="hand a fanout to the in-cluster controller")
    p.add_argument("config")
    p.add_argument("--configmap", default="multirun-config")
    p.add_argument("--namespace", default="multirun")
    p.add_argument("--stamp", help="fix the instance stamp (for reproducibility)")

    p = add("watch", cmd_watch,
            help="the controller loop: watch a config dir, run what appears")
    p.add_argument("config_dir")
    p.add_argument("--runner-image", required=True)
    p.add_argument("--namespace", default="multirun")
    p.add_argument("--creds-dir", default="/creds/claude")
    p.add_argument("--creds-secret", default="claude-creds")
    p.add_argument("--artifacts-root", default="/artifacts")
    p.add_argument("--artifacts-pvc", default="multirun-artifacts")
    p.add_argument("--interval", type=int, default=15)
    p.add_argument("--once", action="store_true",
                   help="one tick, then exit (for smoke-testing the loop)")

    p = add("status", cmd_status)
    p.add_argument("--namespace", default="multirun")

    p = add("logs", cmd_logs)
    p.add_argument("fanout")
    p.add_argument("run")
    p.add_argument("--namespace", default="multirun")

    p = add("teardown", cmd_teardown)
    p.add_argument("--fanout")
    p.add_argument("--sweep", action="store_true",
                   help="delete leaked mr-run-* branches")
    p.add_argument("--project", required=True, help="neon project id")
    p.add_argument("--min-age", type=int, default=3600)
    p.add_argument("--namespace", default="multirun")

    db = sub.add_parser("db").add_subparsers(dest="db_command", required=True)
    db.add_parser("migrate").set_defaults(fn=cmd_db_migrate)

    creds = sub.add_parser("creds").add_subparsers(dest="creds_command",
                                                   required=True)
    p = creds.add_parser("push")
    p.set_defaults(fn=cmd_creds_push)
    p.add_argument("--secret", default="claude-creds")
    p.add_argument("--namespace", default="multirun")

    args = top.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
