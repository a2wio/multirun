# config reference

One yaml per fan-out. Two top-level keys, nothing else:

```yaml
global:   # defaults for every run
runs:     # a non-empty list of deltas; per-run wins on merge
```

## merge rules

- mappings merge key-by-key, recursively: a run saying
  `source: {ref: abc123}` changes only the ref and keeps the global
  repo
- scalars and lists replace whole
- unknown keys are rejected by name, at submit time

## global keys

| key            | required | default        | notes |
|----------------|----------|----------------|-------|
| `name`         | no       | config filename | names the fanout instance |
| `source`       | see note | —              | `{repo, ref, seed?}`; `ref` must be a sha (7–40 hex). Omit to take the task's own `source.yaml`. |
| `task`         | yes      | —              | path to the task dir, e.g. `tasks/add-teams` |
| `model`        | yes      | —              | passed to the Agent SDK as-is (`sonnet`, `opus`, `haiku`, …) |
| `timeout`      | no       | `30m`          | `90s` / `30m` / `2h` / bare seconds |
| `max_parallel` | no       | `3`            | global-only; guards the one shared subscription |
| `neon`         | yes      | —              | `{project, parent_branch?, database?, role?}` |
| `artifacts`    | no       | `artifacts`    | artifact root (local path today) |
| `env`          | no       | `{}`           | non-secret extras for the run |

## per-run keys

Everything from global except `name` and `max_parallel`, plus:

| key      | required | notes |
|----------|----------|-------|
| `id`     | yes      | unique; becomes branch/job/artifact names — `a-z 0-9 - _`, max 16 chars |
| `dotenv` | no       | file of `KEY=VALUE` lines loaded into the run's env |

## what a run actually receives

The runner never sees this file. It reads the *rendered* `run.yaml` —
the merged result for that one run — which is also stored in the run's
artifacts, so "what exactly did run 7 get?" has a file as its answer:

```yaml
fanout: smoke-07281341
run: "1"
model: haiku
timeout_s: 600
source: {repo: ..., ref: ...}
workdir: /work/checkout
artifact_dir: /artifacts
task: {name: smoke, prompt_file: ..., checks_dir: ...}
env: {}
```

`DATABASE_URL` is not in it: connection uris are credentials and
arrive via the environment (per-run Secret in-cluster, process env
locally).
