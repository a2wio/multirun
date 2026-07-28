"""Parent vs branch, DDL.

First choice is pg_dump --schema-only on both sides and a unified diff
— the full truth. When pg_dump is missing or older than the server
(it refuses newer majors), fall back to a catalog walk: tables, columns,
types, defaults, nullability from information_schema. Less complete
(no functions, no triggers), but it never silently returns "no changes"
— the fallback is named in the output so nobody mistakes it for the
full dump.
"""

import difflib
import os
import shutil
import subprocess
from dataclasses import dataclass

_CATALOG_SQL = """
SELECT table_schema || '.' || table_name || '.' || column_name
       || ' ' || data_type
       || CASE WHEN is_nullable = 'NO' THEN ' not null' ELSE '' END
       || COALESCE(' default ' || column_default, '')
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1;
"""


@dataclass
class SchemaDiff:
    changed: bool
    method: str  # pg_dump | catalog
    text: str


def _psql_bin(name: str) -> str | None:
    pgbin = os.environ.get("PGBIN")
    if pgbin:
        candidate = os.path.join(pgbin, name)
        return candidate if os.path.exists(candidate) else None
    return shutil.which(name)


def _pg_dump_schema(uri: str) -> str | None:
    pg_dump = _psql_bin("pg_dump")
    if not pg_dump:
        return None
    proc = subprocess.run(
        [pg_dump, "--schema-only", "--no-owner", "--no-privileges", uri],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return None  # version mismatch or unreachable — caller falls back
    # strip the dump's own noise so identical schemas diff to nothing:
    # comments, and pg_dump 18's per-dump random \restrict tokens
    return "\n".join(line for line in proc.stdout.splitlines()
                     if line.strip() and not line.startswith("--")
                     and not line.startswith(("\\restrict", "\\unrestrict")))


def _catalog_schema(uri: str) -> str:
    psql = _psql_bin("psql") or "psql"
    proc = subprocess.run([psql, uri, "-At", "-v", "ON_ERROR_STOP=1",
                           "-c", _CATALOG_SQL],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"catalog query failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def diff(parent_uri: str, branch_uri: str) -> SchemaDiff:
    parent, branch = _pg_dump_schema(parent_uri), _pg_dump_schema(branch_uri)
    method = "pg_dump"
    if parent is None or branch is None:
        parent, branch = _catalog_schema(parent_uri), _catalog_schema(branch_uri)
        method = "catalog"
    lines = list(difflib.unified_diff(parent.splitlines(), branch.splitlines(),
                                      fromfile=f"parent ({method})",
                                      tofile=f"branch ({method})", lineterm=""))
    return SchemaDiff(changed=bool(lines), method=method,
                      text="\n".join(lines) + ("\n" if lines else ""))
