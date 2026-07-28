#!/usr/bin/env bash
# a teams concept must exist in the database, whatever shape it took —
# a heuristic on purpose: the interesting grading happens in the diffs
set -euo pipefail
count=$("${PSQL:-psql}" "$DATABASE_URL" -Atc "
    SELECT count(*) FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
      AND table_name ILIKE '%team%'")
[ "$count" -ge 1 ]
