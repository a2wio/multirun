"""Rows added / removed per table, parent vs branch.

Method: pull md5(row::text) for every row of every user table on both
sides and compare the multisets in memory. An update therefore shows as
one removed + one added — honest, if blunt; proper keyed change
tracking is deferred until a task needs it. Tables past ROW_CAP rows
get counts only (this is a bench for seeded fixtures, not a data
warehouse).

Tables that exist on one side only are reported under only_in — the
usual signature of an agent that created its own tables.
"""

import os
import shutil
import subprocess
from collections import Counter

ROW_CAP = 10_000


def _psql(uri: str, sql: str) -> list[str]:
    pgbin = os.environ.get("PGBIN")
    psql = os.path.join(pgbin, "psql") if pgbin else (shutil.which("psql") or "psql")
    proc = subprocess.run([psql, uri, "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed: {proc.stderr.strip()[:300]}")
    return [line for line in proc.stdout.splitlines() if line]


def _tables(uri: str) -> list[str]:
    return _psql(uri, """
        SELECT table_schema || '.' || table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY 1;""")


def _count(uri: str, table: str) -> int:
    schema, name = table.split(".", 1)
    return int(_psql(uri, f'SELECT count(*) FROM "{schema}"."{name}";')[0])


def _row_hashes(uri: str, table: str) -> Counter:
    schema, name = table.split(".", 1)
    return Counter(_psql(uri, f'SELECT md5(t::text) FROM "{schema}"."{name}" t;'))


def diff(parent_uri: str, branch_uri: str) -> dict:
    parent_tables, branch_tables = set(_tables(parent_uri)), set(_tables(branch_uri))
    out: dict = {"tables": {}}

    for table in sorted(parent_tables | branch_tables):
        if table not in parent_tables or table not in branch_tables:
            side = "branch" if table not in parent_tables else "parent"
            uri = branch_uri if side == "branch" else parent_uri
            out["tables"][table] = {"only_in": side, "rows": _count(uri, table)}
            continue
        p_count, b_count = _count(parent_uri, table), _count(branch_uri, table)
        if max(p_count, b_count) > ROW_CAP:
            entry = {"parent_rows": p_count, "branch_rows": b_count,
                     "note": f"over {ROW_CAP} rows — counts only"}
        else:
            p_rows, b_rows = _row_hashes(parent_uri, table), _row_hashes(branch_uri, table)
            entry = {"parent_rows": p_count, "branch_rows": b_count,
                     "added": sum((b_rows - p_rows).values()),
                     "removed": sum((p_rows - b_rows).values())}
        out["tables"][table] = entry

    touched = [t for t, d in out["tables"].items()
               if d.get("added") or d.get("removed") or d.get("only_in")]
    out["summary"] = {"tables_total": len(out["tables"]),
                      "tables_touched": len(touched), "touched": touched}
    return out
