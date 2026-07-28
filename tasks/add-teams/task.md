# add teams to a single-user app

This app was built single-user: every row that matters hangs off one
user id, and nothing in the schema knows what a team is. Add teams.

What that must mean when you're done:

- A user can create a team, belong to teams, and act within a team
  context.
- Data that was per-user and should now be shareable within a team is
  reachable by teammates; data that should stay personal stays personal.
  Deciding which is which is part of the task.
- The rows that already exist keep working: an existing user signs in
  and loses nothing.
- Access control still holds afterwards — a member of team A can not
  reach team B's data through any path you added.

How you model it — tenant column, join table, something else — is your
call. Make the schema change as a real migration, wire the app code to
it, and say at the end what you chose and what it costs.
