# smoke — prove the loop

Two small things, then stop:

1. Create `PROOF.md` at the repo root: one line saying which run you
   are (run $run_id), one line listing the files you found in the tree.
2. Insert one row into the `smoke_items` table: source = 'agent',
   note = 'run $run_id'. The database is at $DATABASE_URL; use psql
   (the binary is at $PSQL when that variable is set, plain `psql`
   otherwise).

Don't touch anything else. Done means both exist.
