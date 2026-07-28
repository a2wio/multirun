"""A k8s Job per run.

Manifest generation is pure functions over a RunPlan — testable without
a cluster — and the thin apply_* wrappers at the bottom are the only
place the kubernetes client is touched (lazily imported, so nothing
here needs it installed until you actually spawn).

What a run pod looks like:

- an init container materializes the worktree at the pinned sha into an
  emptyDir (harness.resources.worktree as a module) — so the runner
  container itself acquires nothing;
- the runner container reads /config/run.yaml, drives the Agent SDK on
  subscription auth (the claude-creds Secret mounted as $HOME/.claude),
  and writes artifacts to /artifacts;
- DATABASE_URL arrives via a per-run Secret, never via the ConfigMap —
  connection uris are credentials.
"""

import yaml

from .plan import RunPlan

GRACE_S = 600  # reaper slack past the run's own timeout


def build_run_yaml(p: RunPlan, *, task_name: str,
                   workdir: str = "/work/checkout",
                   artifact_dir: str = "/artifacts") -> str:
    """The exact merged config this run gets — itself a stored artifact."""
    return yaml.safe_dump({
        "fanout": p.fanout,
        "run": p.spec.id,
        "model": p.spec.model,
        "timeout_s": p.spec.timeout_s,
        "source": {"repo": p.spec.source.repo, "ref": p.spec.source.ref},
        "workdir": workdir,
        "artifact_dir": artifact_dir,
        "task": {"name": task_name,
                 "prompt_file": "/config/task.md",
                 "checks_dir": "/config/checks"},
        "env": p.spec.env,
        **({"dotenv": "/config/run.env"} if p.spec.dotenv else {}),
    }, sort_keys=False)


def build_configmap(p: RunPlan, *, task_name: str, task_md: str,
                    checks: dict[str, str] | None = None,
                    namespace: str = "multirun",
                    artifact_dir: str | None = None) -> dict:
    data = {"run.yaml": build_run_yaml(p, task_name=task_name,
                                       artifact_dir=artifact_dir or "/artifacts"),
            "task.md": task_md}
    for name, content in (checks or {}).items():
        data[f"checks__{name}"] = content
    return {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": p.configmap_name, "namespace": namespace,
                         "labels": _labels(p)},
            "data": data}


def build_secret(p: RunPlan, *, database_url: str,
                 namespace: str = "multirun") -> dict:
    return {"apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": p.secret_name, "namespace": namespace,
                         "labels": _labels(p)},
            "type": "Opaque",
            "stringData": {"DATABASE_URL": database_url}}


def build_job(p: RunPlan, *, runner_image: str,
              check_names: list[str] | None = None,
              creds_secret: str = "claude-creds",
              service_account: str = "multirun-runner",
              namespace: str = "multirun",
              artifacts_claim: str | None = None,
              deploy_key_secret: str = "source-deploy-key",
              pull_secret: str = "registry-credentials") -> dict:
    # artifacts: the shared PVC when given (they outlive the pod, and the
    # controller reads them at harvest), an emptyDir when not (local dev
    # against a cluster with no volume — artifacts die with the pod).
    artifacts_volume = (
        {"name": "artifacts",
         "persistentVolumeClaim": {"claimName": artifacts_claim}}
        if artifacts_claim else {"name": "artifacts", "emptyDir": {}})
    volumes = [
        {"name": "config",
         "configMap": {"name": p.configmap_name,
                       "items": _configmap_items(check_names or [])}},
        {"name": "work", "emptyDir": {}},
        artifacts_volume,
        # mounted OUTSIDE $HOME: the CLI needs a writable ~/.claude, so the
        # runner copies the credentials in at start (entrypoint.py)
        {"name": "claude-creds", "secret": {"secretName": creds_secret}},
        # read-only deploy key for private sources; optional so public
        # sources need nothing. ssh rejects the mount's permissions, so the
        # init container copies it private first (worktree.py).
        {"name": "deploy-key",
         "secret": {"secretName": deploy_key_secret, "optional": True,
                    "defaultMode": 0o444}},
    ]
    common_mounts = [
        {"name": "config", "mountPath": "/config", "readOnly": True},
        {"name": "work", "mountPath": "/work"},
    ]
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": p.job_name, "namespace": namespace,
                     "labels": _labels(p)},
        "spec": {
            "backoffLimit": 0,  # a failed run is a result, not a retry
            "ttlSecondsAfterFinished": 3600,
            "activeDeadlineSeconds": p.spec.timeout_s + GRACE_S,
            "template": {
                "metadata": {"labels": _labels(p)},
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": service_account,
                    "imagePullSecrets": [{"name": pull_secret}],
                    "initContainers": [{
                        "name": "worktree",
                        "image": runner_image,
                        "command": ["python", "-m", "harness.resources.worktree",
                                    "/config/run.yaml", "/work"],
                        "env": [{"name": "MULTIRUN_DEPLOY_KEY",
                                 "value": "/deploy-key/key"}],
                        "volumeMounts": common_mounts + [
                            {"name": "deploy-key", "mountPath": "/deploy-key",
                             "readOnly": True},
                        ],
                        "resources": {
                            "requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"memory": "512Mi"},
                        },
                    }],
                    "containers": [{
                        "name": "runner",
                        "image": runner_image,
                        "command": ["multirun-runner", "/config/run.yaml"],
                        "env": [
                            {"name": "HOME", "value": "/home/agent"},
                            {"name": "MULTIRUN_CLAUDE_CREDS",
                             "value": "/creds/claude/.credentials.json"},
                        ],
                        "envFrom": [{"secretRef": {"name": p.secret_name}}],
                        "volumeMounts": common_mounts + [
                            {"name": "artifacts", "mountPath": "/artifacts"},
                            {"name": "claude-creds",
                             "mountPath": "/creds/claude",
                             "readOnly": True},
                        ],
                        # the node is small and shared: requests keep the
                        # scheduler honest, the memory limit keeps a runaway
                        # npm build from evicting the neighbors
                        "resources": {
                            "requests": {"cpu": "500m", "memory": "512Mi"},
                            "limits": {"memory": "2Gi"},
                        },
                    }],
                    "volumes": volumes,
                },
            },
        },
    }


def _labels(p: RunPlan) -> dict:
    return {"app": "multirun", "multirun/fanout": p.fanout,
            "multirun/run": str(p.spec.id)}


def _configmap_items(check_names: list[str]) -> list[dict]:
    # checks__<name> keys re-materialize as files under /config/checks/
    # (configmap keys can't contain slashes; volume items put them back)
    return ([{"key": "run.yaml", "path": "run.yaml"},
             {"key": "task.md", "path": "task.md"}]
            + [{"key": f"checks__{n}", "path": f"checks/{n}"}
               for n in check_names])


# -- the only place the kubernetes client is touched --------------------------

def apply(manifests: list[dict], namespace: str = "multirun") -> None:
    from kubernetes import client, config, utils
    config.load_incluster_config() if _in_cluster() else config.load_kube_config()
    utils.create_from_dict(client.ApiClient(), {"apiVersion": "v1", "kind": "List",
                                                "items": manifests},
                           namespace=namespace)


def job_status(job_name: str, namespace: str = "multirun") -> str:
    """pending | running | succeeded | failed | gone"""
    from kubernetes import client, config
    config.load_incluster_config() if _in_cluster() else config.load_kube_config()
    try:
        job = client.BatchV1Api().read_namespaced_job_status(job_name, namespace)
    except Exception:
        return "gone"
    s = job.status
    if s.succeeded:
        return "succeeded"
    if s.failed:
        return "failed"
    return "running" if s.active else "pending"


def delete_job(job_name: str, namespace: str = "multirun") -> None:
    from kubernetes import client, config
    config.load_incluster_config() if _in_cluster() else config.load_kube_config()
    try:
        client.BatchV1Api().delete_namespaced_job(
            job_name, namespace, propagation_policy="Foreground")
    except Exception:
        pass  # already gone is the goal state


def _in_cluster() -> bool:
    import os
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")
