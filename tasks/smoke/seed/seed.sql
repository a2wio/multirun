-- seeded state lives on the task's parent branch: every run branches
-- off it, so the diff against the parent is exactly what the agent did
CREATE TABLE IF NOT EXISTS smoke_items (
    id         serial PRIMARY KEY,
    source     text NOT NULL,
    note       text,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO smoke_items (source, note) VALUES
    ('seed', 'fixture row one'),
    ('seed', 'fixture row two');
