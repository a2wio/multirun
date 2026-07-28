-- run history, queryable in SQL — that's the point of this db.

CREATE TABLE IF NOT EXISTS fanouts (
    fanout       text PRIMARY KEY,          -- instance name, e.g. smoke-07281341
    name         text NOT NULL,             -- the config's own name
    config_yaml  text NOT NULL,             -- the submitted yaml, verbatim
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    fanout       text NOT NULL,
    run_id       text NOT NULL,
    state        text NOT NULL,
    model        text,
    exit_reason  text,
    num_turns    int,
    wall_seconds numeric,
    tokens_in    bigint,
    tokens_out   bigint,
    meta         jsonb,                     -- the run's meta.json, whole
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fanout, run_id)
);

-- every state transition, append-only: the run's biography
CREATE TABLE IF NOT EXISTS events (
    id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fanout  text NOT NULL,
    run_id  text NOT NULL,
    state   text NOT NULL,
    at      timestamptz NOT NULL DEFAULT now()
);

-- teardown is a first-class state with its own record: what each run
-- held, and whether it was given back
CREATE TABLE IF NOT EXISTS resources (
    fanout      text NOT NULL,
    run_id      text NOT NULL,
    kind        text NOT NULL,              -- neon-branch | worktree | ...
    status      text NOT NULL,              -- acquired | released | leaked
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (fanout, run_id, kind)
);

CREATE INDEX IF NOT EXISTS events_run_idx ON events (fanout, run_id, at);
CREATE INDEX IF NOT EXISTS resources_leaked_idx ON resources (status)
    WHERE status <> 'released';
