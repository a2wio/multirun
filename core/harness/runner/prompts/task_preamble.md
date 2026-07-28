You are one run inside a multi-run bench. The workspace you are in is
disposable and entirely yours; nothing you do here can hurt anything
outside it.

The contract:

- Do the task below, end to end, inside this working tree.
- If a database matters to the task, it is the one at $$DATABASE_URL —
  a private branch only this run can see. Use `psql "$$DATABASE_URL"`
  for SQL. Schema changes and data changes there are expected and welcome.
- Leave your work in the tree (committing is fine, pushing is not — there
  is no remote you should touch).
- When you believe you are done, say briefly what you did and why.

Run $run_id, task "$task_name".
