"""The shapes run history is stored in. Plain rows, no ORM — he wants
run history queryable in SQL, so SQL is the interface, and these are
just the names Python uses for it."""

from dataclasses import dataclass
from enum import StrEnum


class RunState(StrEnum):
    PENDING = "pending"
    PROVISIONING = "provisioning"
    SPAWNED = "spawned"
    RUNNING = "running"
    DIFFING = "diffing"
    TEARDOWN = "teardown"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class RunRow:
    fanout: str
    run_id: str
    state: str
    model: str | None = None
    branch_name: str | None = None
    artifact_dir: str | None = None
    exit_reason: str | None = None
    num_turns: int | None = None
    wall_seconds: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
