#!/usr/bin/env bash
# one row from the agent in smoke_items, on this run's own branch
set -euo pipefail
count=$("${PSQL:-psql}" "$DATABASE_URL" -Atc \
    "SELECT count(*) FROM smoke_items WHERE source = 'agent'")
[ "$count" -ge 1 ]
