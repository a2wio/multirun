"""One config -> N run plans -> k8s manifests, all pure, all pinnable."""

import yaml

from harness.config.schema import parse_config
from harness.orchestrator import plan as plan_mod
from harness.orchestrator import spawn

CONFIG = {
    "global": {
        "name": "bench",
        "source": {"repo": "https://github.com/kubeden/app.git", "ref": "a" * 40},
        "task": "tasks/add-teams",
        "model": "sonnet",
        "timeout": "10m",
        "neon": {"project": "proj-123"},
    },
    "runs": [{"id": "1"}, {"id": "2", "model": "opus"}],
}


def plans():
    return plan_mod.plan(parse_config(CONFIG), stamp="0728")


def test_one_spec_per_run_variants_kept():
    p1, p2 = plans()
    assert p1.spec.model == "sonnet" and p2.spec.model == "opus"
    assert p1.fanout == p2.fanout == "bench-0728"


def test_derived_names_are_fingerprintable():
    p = plans()[0]
    assert p.branch_name == "mr-run-bench-0728-1"  # what the reaper greps for
    assert p.job_name == "mr-bench-0728-1"
    assert p.configmap_name == "mr-bench-0728-1-config"
    assert p.artifact_prefix == "bench-0728/1"


def test_instance_name_slugs_hostile_config_names():
    assert plan_mod.instance_name("My Bench!!", stamp="0728") == "my-bench-0728"


def test_run_yaml_is_the_complete_runner_contract():
    got = yaml.safe_load(spawn.build_run_yaml(plans()[1], task_name="add-teams"))
    assert got == {
        "fanout": "bench-0728", "run": "2", "model": "opus", "timeout_s": 600,
        "source": {"repo": "https://github.com/kubeden/app.git", "ref": "a" * 40},
        "workdir": "/work/checkout", "artifact_dir": "/artifacts",
        "task": {"name": "add-teams", "prompt_file": "/config/task.md",
                 "checks_dir": "/config/checks"},
        "env": {},
    }


def test_database_url_never_lands_in_the_configmap():
    cm = spawn.build_configmap(plans()[0], task_name="add-teams",
                               task_md="do the thing")
    assert "DATABASE_URL" not in yaml.safe_dump(cm)
    secret = spawn.build_secret(plans()[0], database_url="postgres://x")
    assert secret["stringData"]["DATABASE_URL"] == "postgres://x"


def test_checks_ride_the_configmap_and_remap_to_files():
    p = plans()[0]
    cm = spawn.build_configmap(p, task_name="t", task_md="x",
                               checks={"01-build.sh": "exit 0"})
    assert cm["data"]["checks__01-build.sh"] == "exit 0"
    job = spawn.build_job(p, runner_image="img", check_names=["01-build.sh"])
    items = job["spec"]["template"]["spec"]["volumes"][0]["configMap"]["items"]
    assert {"key": "checks__01-build.sh", "path": "checks/01-build.sh"} in items


def test_job_shape():
    p = plans()[0]
    job = spawn.build_job(p, runner_image="registry/runner:1")
    spec = job["spec"]
    assert spec["backoffLimit"] == 0  # a failed run is a result, not a retry
    assert spec["activeDeadlineSeconds"] == 600 + spawn.GRACE_S
    pod = spec["template"]["spec"]
    assert pod["restartPolicy"] == "Never"
    init = pod["initContainers"][0]
    assert init["command"][:3] == ["python", "-m", "harness.resources.worktree"]
    runner = pod["containers"][0]
    assert runner["command"] == ["multirun-runner", "/config/run.yaml"]
    assert runner["envFrom"] == [{"secretRef": {"name": p.secret_name}}]


def test_no_api_key_path_anywhere_in_the_job():
    job = spawn.build_job(plans()[0], runner_image="img")
    assert "ANTHROPIC_API_KEY" not in yaml.safe_dump(job)
    mounts = job["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
    creds = [m for m in mounts if m["name"] == "claude-creds"]
    assert creds and creds[0]["mountPath"] == "/home/agent/.claude"
    assert creds[0]["readOnly"] is True


def test_labels_carry_the_fingerprint():
    job = spawn.build_job(plans()[0], runner_image="img")
    assert job["metadata"]["labels"]["multirun/fanout"] == "bench-0728"
    assert job["metadata"]["labels"]["multirun/run"] == "1"
