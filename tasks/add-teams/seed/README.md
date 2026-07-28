# seeds — small fixtures only

`.sql` files here run once, in name order, on this task's parent
branch (`mr-parent-add-teams`). Every run branches off that, so all N
agents see identical seeded state and the diff against the parent is
exactly what each agent did.

`seed.sql` is the template's world before teams: its schema at the
pinned sha (neon_auth recreated, the 0000 migration applied, drizzle's
journal agreeing), plus three users with profiles and assets — enough
that "existing rows keep working" is testable, and no more. A seed that
takes minutes to load slows every fan-out; bulk data belongs in a
snapshot, not here.

Changing fixtures means a new task name or deleting the parent branch
first — an existing parent is reused as-is.
