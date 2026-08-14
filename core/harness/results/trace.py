"""What a run actually did, read back out of its own trace.

Every message is appended to trace.jsonl as it streams, so the trace
survives things the recorded meta.json does not — including a run that
died before writing one at all.

It is worth reading back because a session can end more than once. The
SDK emits a ResultMessage per segment, and `num_turns`, `usage` and
`duration_ms` are all per-segment: a run that segmented and then had
only its last ResultMessage recorded reports the tail as if it were the
whole thing. `total_cost_usd` is the exception — the SDK reports it
cumulative per session — so the rule here is sum the counters and keep
the last cost.

Read-only and offline: point it at an artifacts directory, get the
per-run truth back. `recorded_num_turns` comes from each run's
meta.json when it wrote one, which is what makes a disagreement with
`num_turns` visible instead of theoretical.
"""

import json
from pathlib import Path


def _accumulate_usage(acc: dict, usage: dict) -> None:
    """Sum every integer counter, nested ones included — the SDK adds
    fields over time and a counter nobody thought to list is still a
    counter."""
    for key, value in (usage or {}).items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            acc[key] = acc.get(key, 0) + value
        elif isinstance(value, dict):
            nested = acc.setdefault(key, {})
            if isinstance(nested, dict):
                _accumulate_usage(nested, value)


def totals(trace_path: Path) -> dict:
    """Accumulate one run's trace into the numbers it should have recorded."""
    segments = []
    assistant = 0
    last_type = None
    with Path(trace_path).open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # a trace cut mid-write ends in half a line
            kind = entry.get("type")
            last_type = kind
            if kind == "AssistantMessage":
                assistant += 1
            elif kind == "ResultMessage":
                segments.append(entry.get("message") or {})

    usage: dict = {}
    turns = duration_ms = 0
    cost = None
    is_error = None
    for seg in segments:
        turns += seg.get("num_turns") or 0
        duration_ms += seg.get("duration_ms") or 0
        _accumulate_usage(usage, seg.get("usage") or {})
        if seg.get("total_cost_usd") is not None:
            cost = seg["total_cost_usd"]
        is_error = bool(seg.get("is_error"))

    return {
        "segments": len(segments),
        "num_turns": turns,
        "agent_duration_ms": duration_ms,
        "usage": usage,
        "total_cost_usd": cost,
        "is_error": is_error,
        # a trace whose last line is not a ResultMessage was cut off: the
        # run died mid-agent and whatever it did after that line is gone
        "complete": last_type == "ResultMessage",
        "assistant_messages": assistant,
        "last_message": last_type,
        "trace_bytes": Path(trace_path).stat().st_size,
    }


def walk(artifacts_dir: Path) -> list[dict]:
    """Every run under one instance's artifacts, in id order. Runs with no
    trace are listed rather than skipped — a run that produced nothing is
    a finding, not an absence."""
    root = Path(artifacts_dir)
    rows = []
    for run_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        trace = run_dir / "trace.jsonl"
        if not trace.is_file():
            rows.append({"run": run_dir.name, "segments": 0, "trace": None})
            continue
        row = {"run": run_dir.name, **totals(trace)}
        meta = run_dir / "meta.json"
        if meta.is_file():
            try:
                recorded = json.loads(meta.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                recorded = {}
            row["recorded_num_turns"] = recorded.get("num_turns")
        else:
            row["recorded_num_turns"] = None  # died before writing one
        rows.append(row)
    return rows
