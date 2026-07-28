# multirun — design

Point it at a source (a repo at a commit), give it a task, and it fans
out N isolated runs of a coding agent — each run gets its own git
worktree AND its own Neon database branch — then captures what each
run did and lets you compare them side by side.

The db-branch-per-run is the whole point. All N runs start from
byte-identical database state because they all branch off the same
parent, copy-on-write. Diffing each branch back against the parent
tells you what the agent actually did to the data, instead of reading
N transcripts.

## The abstraction

    run = (source, task, variant) -> artifacts

and everything else is a view over artifacts.

- **source** — repo url + ref (a sha), plus an optional db seed. Never
  vendored into this repo: vendoring goes stale, and the comparability
  of runs depends on all of them starting from the same sha. A task
  names its source in `source.yaml`; a fan-out config can override it.
- **task** — a prompt (markdown) plus its checks, versioned as files
  under `tasks/`. An old task can be rerun against a newer source.
- **variant** — what differs per run: model, prompt variant, extra env,
  or nothing at all when the point is measuring variance between
  identical runs.
- **artifacts** — the run's complete output: the rendered config it
  got, the agent trace, the git diff, the db diffs, check results,
  tokens and timing, and the resource ledger. `runner/capture.py` and
  `resources/storage.py` say exactly what lands where.

## States a run moves through

    PENDING -> PROVISIONING -> SPAWNED -> RUNNING -> DIFFING
            -> TEARDOWN -> DONE | FAILED

- **PROVISIONING** — orchestrator work: the Neon branch is created off
  the task's parent, the artifact prefix exists, the rendered config
  is stored.
- **RUNNING** — the runner owns the run. It is deliberately dumb: it
  reads `/config/run.yaml`, drives the agent, writes artifacts. It
  never talks to the k8s api, never talks to the Neon api, never
  imports orchestrator code. Config in, artifacts out is the entire
  contract — that's what keeps a failed pod debuggable.
- **DIFFING** — orchestrator again: branch vs parent, schema and data.
  Happens before teardown because the diff needs the branch alive.
- **TEARDOWN is a first-class state with its own record**, not a
  finally block. It runs on success, failure and timeout alike; every
  acquire and release lands in the run's ledger (`ledger.jsonl`) and
  the results db. Leaked branches bill monthly and nobody notices —
  so "was everything given back" must be answerable in SQL months
  later, and the reaper sweeps whatever a crash still leaked.

A failed run is a result, not a retry: `backoffLimit: 0`, and the
failure artifacts are the product.

## Config: global + per-run overlay

One yaml defines a fan-out. `global:` is defaults, `runs:` is a list
of deltas, per-run wins on merge. Mappings merge key-by-key,
recursively; scalars and lists replace whole (`config/merge.py`).
Validation is strict: unknown keys are named and rejected at submit
time (`config/schema.py`), because a typo three branches into a
fan-out is ten branches of wasted subscription.

`max_parallel` is global-only by construction — it guards one shared
subscription, so a single run has no business raising it.

The merged result for each run is rendered and stored as `run.yaml` in
that run's artifacts: "what exactly did run 7 get?" must be answerable
months later, from the artifact, not from replaying the merge.

## Resources: acquire() / release()

Everything a run borrows from the world sits behind the same two verbs
(`resources/base.py`): the Neon branch, the git worktree, the artifact
prefix. Adding "and a k8s namespace" later is one new file in
`resources/`, not a runner rewrite.

- acquire is idempotent: re-acquiring for the same run converges on
  the same resource.
- release is idempotent and tolerant: called twice, or called for a
  resource that never finished acquiring, it does nothing loudly.
- acquisition order reverses on release; a failed acquire releases
  what was already held.
- facts a resource returns may carry credentials (connection uris);
  those are marked `secret_` and flow to the run's environment only —
  never the ledger, never the logs, never a ConfigMap.

### Seeded parents

A task with seed fixtures gets its own parent branch
(`mr-parent-<task>`), created once off the configured parent and
seeded via psql. Runs branch off that. The seed therefore lives
upstream of every run, and branch-vs-parent stays exactly "what the
agent did". Parent branches are kept between fan-outs (one cheap
branch per task); the sweep can reap them.

## The Agent SDK constraint

The runner drives the agent through Anthropic's Agent SDK (headless
Claude Code), NOT the raw api. Denis pays with his Claude
subscription; ten model-runs through the api would be real money.
There is no `ANTHROPIC_API_KEY` path anywhere in the runner — the
variable is actively stripped from the agent's environment
(`runner/agent.py`) so the wrong path is impossible, not just
discouraged.

Two consequences, both handled:

1. **Credential rotation.** Subscription auth in a pod means the CLI's
   OAuth credentials mounted as a Secret, and those rotate. A stale
   Secret makes every run fail auth with nothing obvious in the logs.
   So: `multirun creds push` seeds the Secret from the local login;
   the controller checks freshness (`creds_stale`, pure) and
   refreshes by running one no-op CLI turn on a writable copy of the
   creds — the CLI does its own oauth refresh — then pushes the
   rotated file back into the Secret (`refresh_creds`). Creds are
   never baked into an image.
2. **Concurrency limits.** Ten simultaneous runs on one subscription
   will hit rate limits. `max_parallel` (default 3) caps in-flight
   runs and the orchestrator queues the rest. Ten branches does not
   mean ten at once.

## On the cluster

`core` is a controller: a plain Deployment, no CRD, no operator
boilerplate. Run state lives in the results database, not in etcd —
run history is meant to be queried in SQL, not `kubectl get`.

One k8s Job per run (`orchestrator/spawn.py`). The pod:

- an init container materializes the worktree at the pinned sha into
  an emptyDir (`resources/worktree.py` as a module) — so the runner
  container starts from an existing checkout and acquires nothing;
- the runner container reads `/config/run.yaml` from a per-run
  ConfigMap; `DATABASE_URL` arrives via a per-run Secret because
  connection uris are credentials;
- subscription creds mount read-only at `$HOME/.claude`.

The controller loop (`orchestrator/controller.py`) spawns up to
`max_parallel`, polls, diffs, tears down, records. The reaper
(`orchestrator/reaper.py`) kills overdue jobs past timeout + grace and
sweeps leaked branches. Job manifests are pure functions with tests.

The controller's front door is `orchestrator/watch.py`: the Deployment
runs `multirun watch /etc/multirun`, and `multirun publish <config>`
hands it work by rendering the config into a ConfigMap with a stamp.
The stamp names the fanout instance deterministically, and the results
db is the cross-restart memory — a restarted controller skips instances
it already knows and leaves their leftovers to the reaper. The watch
loop also owns credential freshness (below), because it is the one
place that runs forever.

Run artifacts outlive their pods on a shared PVC: the runner writes
its dir, the controller writes the db diffs into the same dir at
harvest and lifts `meta.json` into the results db. Private sources
clone with a read-only deploy key the init container prepares itself
(`resources/worktree.py`) — the key Secret is optional, public sources
need nothing.

## The local path

`multirun local <config>` runs ONE run end to end on this machine:
worktree + Neon branch + agent + capture + db diff + teardown, no
cluster anywhere. It exists so the loop is provable — and stays
provable — without touching k3s. It is the same code the controller
drives: `run_local` and `Controller` share resources, runner, capture
and plan.

## The results db

Itself on Neon (`RESULTS_DATABASE_URL`). Four tables
(`results/migrations/`): fanouts (the submitted yaml, verbatim), runs
(state + tokens + timing + the whole meta.json as jsonb), events
(append-only state transitions — the run's biography), resources
(what each run held and whether it was given back). Unset the env var
and everything still runs — artifacts are the source of truth, the db
is the queryable view.

## Deliberately deferred

- **The results dashboard**: the schema is the contract; views come
  later.
- **Keyed data diffs**: `data_diff.py` compares row-hash multisets, so
  an update reads as one removed + one added. Honest, blunt; proper
  pk-based change tracking waits for a task that needs it.
- **Prompt variants as first-class variant axis**: today a variant is
  model/env/dotenv; per-run prompt overrides ride on tasks, not on
  config keys.
- **Object storage for artifacts**: they live on a single-node PVC;
  when the cluster grows past one node, `resources/storage.py` is
  still the one file that changes.
- **Resuming a fanout the controller crashed out of**: a restart
  skips it and the reaper sweeps; the runs it never spawned are simply
  missing from the results. Rerun the config if they matter.
