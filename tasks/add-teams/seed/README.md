# seeds — small fixtures only

`.sql` files here run once, in name order, on this task's parent
branch (`mr-parent-add-teams`). Every run branches off that, so all N
agents see identical seeded state and the diff against the parent is
exactly what each agent did.

What belongs here for add-teams once the template is pinned: a handful
of users and a few rows of their per-user data — enough that "existing
rows keep working" is testable, and no more. A seed that takes minutes
to load slows every fan-out; bulk data belongs in a snapshot, not here.
