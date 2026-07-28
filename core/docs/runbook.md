# runbook

## prove the loop (local, one run, no cluster)

```sh
cd multirun
python -m venv .venv && .venv/bin/pip install -e "core[dev,results]"
export NEON_API_KEY=...            # console.neon.tech -> account -> api keys
export PGBIN=/opt/homebrew/opt/libpq/bin   # wherever psql/pg_dump live
export PSQL=$PGBIN/psql
.venv/bin/multirun local core/configs/smoke.yaml
```

What you should see: a worktree materializes, a `mr-run-…` branch
appears in the Neon project, the agent does the smoke task, checks
pass, `schema.diff` / `data_diff.json` land in the artifact dir, the
branch is deleted, and the summary prints `branch_gone: true`.

Artifacts: `artifacts/<fanout>/<run>/` — `run.yaml`, `trace.jsonl`,
`diff.patch`, `schema.diff`, `data_diff.json`, `checks.json`,
`meta.json`, `ledger.jsonl`, `run.log`.

## the results db

```sh
export RESULTS_DATABASE_URL=...    # the multirun Neon project's default branch
.venv/bin/multirun db migrate
```

With the env var set, every run records itself. Useful queries:

```sql
-- what happened lately
SELECT fanout, run_id, state, exit_reason, wall_seconds, tokens_out
FROM runs ORDER BY updated_at DESC LIMIT 20;

-- anything still holding a resource?
SELECT * FROM resources WHERE status <> 'released';

-- one run's biography
SELECT state, at FROM events WHERE fanout = ? AND run_id = ? ORDER BY at;
```

## leaked branches

The ledger and the results db say what should exist; Neon says what
does. Reconcile:

```sh
.venv/bin/multirun teardown --sweep --project <neon-project-id>
```

Deletes `mr-run-*` branches older than an hour that no live run owns.
`mr-parent-<task>` branches are kept on purpose (seeded state, one per
task, cheap); pass them to the Neon console/api if a task is retired.

## when a run fails

Everything is in the artifact dir. `run.log` is the runner's own
account; `trace.jsonl` is every agent message; `checks.json` says what
failed; `ledger.jsonl` says whether teardown got everything back. A
run that failed auth almost certainly means stale subscription creds —
locally, any `claude -p` turn refreshes them; on the cluster,
`multirun creds push`.

## the smoke task is the canary

After any change to the harness, `multirun local core/configs/smoke.yaml`
is the two-minute answer to "did I break the loop". It uses a tiny
public repo and a haiku-class model on purpose: the loop is the thing
under test, not the agent.
