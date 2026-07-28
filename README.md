# multirun

Point it at a source (a repo at a commit), give it a task, and it fans
out N isolated runs of a coding agent — each run gets its own git
worktree and its own Neon database branch — then captures what each
run did and lets you compare them side by side.

The db-branch-per-run is the point: all N runs start from
byte-identical database state, so diffing each branch back against the
parent tells you what the agent actually did to the data, instead of
reading N transcripts.

    run = (source, task, variant) -> artifacts

Agents run through Anthropic's Agent SDK on subscription auth — there
is no api-key path anywhere in the runner.

## layout

    core/            the python package (harness/), its docs and tests
      harness/
        cli.py           submit / status / logs / teardown, and `local`
        config/          schema + global/per-run merge
        orchestrator/    plan -> spawn (k8s job per run) -> reap
        runner/          the deliberately dumb part: config in, artifacts out
        resources/       acquire()/release(): neon branch, worktree, storage
        diff/            branch vs parent: schema and rows
        results/         run history, on Neon, queryable in SQL
    tasks/           content, not code: one dir per task (prompt, source, seed, checks)
    dashboard/       the read-only web ui: results db + artifacts volume, htmx, no build step
    infrastructure/  images, chart, argocd — written; deploying is its own phase

## start here

`core/docs/design.md` for how it thinks, `core/docs/runbook.md` to run
the smoke loop on your machine, `core/docs/config-reference.md` for
the yaml.

```sh
python -m venv .venv && .venv/bin/pip install -e "core[dev,results]"
.venv/bin/multirun local core/configs/smoke.yaml
```
