"""The meta db — run state lives here, not in etcd, because he wants
run history queryable in SQL. Itself on Neon (RESULTS_DATABASE_URL);
psycopg is imported lazily so the runner image never needs it.

When RESULTS_DATABASE_URL is unset, Results.open() hands back a null
recorder: every artifact still lands on disk, you just don't get the
SQL view. A local smoke run should never require standing up a db
first — but with the env set, it records like the real thing.
"""

import json
from pathlib import Path

import yaml

MIGRATIONS = Path(__file__).parent / "migrations"


class Results:
    """Thin recorder. All writes are idempotent upserts keyed on
    (fanout, run_id) so re-recording a transition is harmless.

    The connection is long-lived but the server is serverless: Neon
    idles connections out under a watch loop that ticks for days. Every
    operation retries once on a dead connection, against a fresh one —
    idempotent writes make the retry safe."""

    def __init__(self, uri: str):
        import psycopg
        self._psycopg = psycopg
        self._uri = uri
        self._conn = psycopg.connect(uri, autocommit=True)

    @classmethod
    def open(cls, uri: str | None) -> "Results | NullResults":
        return cls(uri) if uri else NullResults()

    def _retry(self, op):
        try:
            return op()
        except self._psycopg.OperationalError:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001 — it's already dead
                pass
            self._conn = self._psycopg.connect(self._uri, autocommit=True)
            return op()

    def migrate(self) -> list[str]:
        return self._retry(self._migrate)

    def _migrate(self) -> list[str]:
        applied = []
        with self._conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations
                           (name text PRIMARY KEY,
                            applied_at timestamptz DEFAULT now())""")
            for sql_file in sorted(MIGRATIONS.glob("*.sql")):
                cur.execute("SELECT 1 FROM schema_migrations WHERE name = %s",
                            (sql_file.name,))
                if cur.fetchone():
                    continue
                cur.execute(sql_file.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO schema_migrations (name) VALUES (%s)",
                            (sql_file.name,))
                applied.append(sql_file.name)
        return applied

    def fanout(self, fanout: str, cfg) -> None:
        def op():
            with self._conn.cursor() as cur:
                cur.execute("""INSERT INTO fanouts (fanout, name, config_yaml)
                               VALUES (%s, %s, %s)
                               ON CONFLICT (fanout) DO NOTHING""",
                            (fanout, cfg.name, yaml.safe_dump(cfg.raw)))
        self._retry(op)

    def fanout_exists(self, fanout: str) -> bool:
        """The watch loop's cross-restart memory: was this instance run?"""
        def op():
            with self._conn.cursor() as cur:
                cur.execute("SELECT 1 FROM fanouts WHERE fanout = %s", (fanout,))
                return cur.fetchone() is not None
        return self._retry(op)

    def state(self, fanout: str, run_id: str, state) -> None:
        return self._retry(lambda: self._state(fanout, run_id, state))

    def _state(self, fanout: str, run_id: str, state) -> None:
        state = getattr(state, "value", state)
        with self._conn.cursor() as cur:
            cur.execute("""INSERT INTO runs (fanout, run_id, state)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (fanout, run_id)
                           DO UPDATE SET state = EXCLUDED.state,
                                         updated_at = now()""",
                        (fanout, run_id, state))
            cur.execute("""INSERT INTO events (fanout, run_id, state)
                           VALUES (%s, %s, %s)""", (fanout, run_id, state))

    def resource(self, fanout: str, run_id: str, kind: str, status: str) -> None:
        return self._retry(lambda: self._resource(fanout, run_id, kind, status))

    def _resource(self, fanout: str, run_id: str, kind: str, status: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("""INSERT INTO resources (fanout, run_id, kind, status)
                           VALUES (%s, %s, %s, %s)
                           ON CONFLICT (fanout, run_id, kind)
                           DO UPDATE SET status = EXCLUDED.status,
                                         updated_at = now()""",
                        (fanout, run_id, kind, status))

    def finish(self, fanout: str, run_id: str, meta: dict) -> None:
        return self._retry(lambda: self._finish(fanout, run_id, meta))

    def _finish(self, fanout: str, run_id: str, meta: dict) -> None:
        usage = meta.get("usage") or {}
        with self._conn.cursor() as cur:
            cur.execute("""UPDATE runs SET
                             model = %s, exit_reason = %s, num_turns = %s,
                             wall_seconds = %s, tokens_in = %s, tokens_out = %s,
                             meta = %s, updated_at = now()
                           WHERE fanout = %s AND run_id = %s""",
                        (meta.get("model"), meta.get("exit_reason"),
                         meta.get("num_turns"), meta.get("wall_seconds"),
                         usage.get("input_tokens"), usage.get("output_tokens"),
                         json.dumps(meta), fanout, run_id))


class NullResults:
    """No RESULTS_DATABASE_URL, no records — and no crashes."""

    def migrate(self) -> list[str]:
        return []

    def fanout(self, *a, **k) -> None:
        pass

    def fanout_exists(self, *a, **k) -> bool:
        return False  # no db, no memory — the watch loop warns about this

    def state(self, *a, **k) -> None:
        pass

    def resource(self, *a, **k) -> None:
        pass

    def finish(self, *a, **k) -> None:
        pass
