// Every query the dashboard runs, in one place. The results db is the
// source of truth for state; the artifacts volume is the source of
// truth for content. Nothing here writes — the role shouldn't let it
// anyway.

import pg from "pg";

const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  max: 5,
  idleTimeoutMillis: 30_000,
});

const ACTIVE = "('pending','provisioning','spawned','running','diffing','teardown')";

export async function instances() {
  const { rows } = await pool.query(`
    SELECT f.fanout, f.name, f.created_at,
           count(r.run_id)::int                                    AS runs,
           count(*) FILTER (WHERE r.state = 'done')::int           AS done,
           count(*) FILTER (WHERE r.state = 'failed')::int         AS failed,
           count(*) FILTER (WHERE r.state IN ${ACTIVE})::int       AS active,
           coalesce(sum(r.tokens_out), 0)::bigint                  AS tokens_out,
           round(avg(r.wall_seconds))                              AS avg_wall,
           coalesce(sum((r.meta ->> 'checks_passed')::int), 0)::int AS checks_passed,
           coalesce(sum((r.meta ->> 'checks_total')::int), 0)::int  AS checks_total,
           max(r.updated_at)                                       AS last_activity
    FROM fanouts f
    LEFT JOIN runs r USING (fanout)
    GROUP BY f.fanout, f.name, f.created_at
    ORDER BY f.created_at DESC`);
  return rows;
}

export async function instance(fanout) {
  const [meta, runs, leaks] = await Promise.all([
    pool.query("SELECT * FROM fanouts WHERE fanout = $1", [fanout]),
    pool.query(
      `SELECT * FROM runs WHERE fanout = $1
       ORDER BY length(run_id), run_id`,
      [fanout],
    ),
    pool.query(
      `SELECT run_id, kind, status, updated_at FROM resources
       WHERE fanout = $1 AND status <> 'released'
       ORDER BY run_id, kind`,
      [fanout],
    ),
  ]);
  return { meta: meta.rows[0], runs: runs.rows, leaks: leaks.rows };
}

export async function run(fanout, runId) {
  const [runRow, events] = await Promise.all([
    pool.query("SELECT * FROM runs WHERE fanout = $1 AND run_id = $2", [
      fanout,
      runId,
    ]),
    pool.query(
      `SELECT state, at FROM events
       WHERE fanout = $1 AND run_id = $2 ORDER BY at, id`,
      [fanout, runId],
    ),
  ]);
  return { run: runRow.rows[0], events: events.rows };
}

export async function activeRuns() {
  const { rows } = await pool.query(`
    SELECT * FROM runs WHERE state IN ${ACTIVE}
    ORDER BY updated_at DESC`);
  return rows;
}

export async function recentRuns(limit = 15) {
  const { rows } = await pool.query(
    `SELECT * FROM runs WHERE state IN ('done','failed')
     ORDER BY updated_at DESC LIMIT $1`,
    [limit],
  );
  return rows;
}

export async function runState(fanout, runId) {
  const { rows } = await pool.query(
    "SELECT state FROM runs WHERE fanout = $1 AND run_id = $2",
    [fanout, runId],
  );
  return rows[0]?.state ?? null;
}
