"""Reading a run's numbers back out of its trace."""

import json

from harness.results import trace


def _write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for kind, message in entries:
            f.write(json.dumps({"type": kind, "message": message}) + "\n")


def _result(turns, out_tok, *, cost, duration_ms=1000):
    return ("ResultMessage", {"num_turns": turns, "duration_ms": duration_ms,
                              "is_error": False, "total_cost_usd": cost,
                              "usage": {"output_tokens": out_tok,
                                        "input_tokens": 10,
                                        "cache_read_input_tokens": 5}})


def test_one_segment_is_reported_as_it_stands(tmp_path):
    t = tmp_path / "trace.jsonl"
    _write(t, [("AssistantMessage", {}), _result(76, 45_000, cost=2.88)])
    got = trace.totals(t)
    assert (got["segments"], got["num_turns"]) == (1, 76)
    assert got["usage"]["output_tokens"] == 45_000
    assert got["total_cost_usd"] == 2.88
    assert got["complete"] is True


def test_segments_sum_but_cost_is_the_last_one(tmp_path):
    # the counters are per-segment, total_cost_usd is cumulative per
    # session — summing it would double-count the first segment
    t = tmp_path / "trace.jsonl"
    _write(t, [_result(162, 103_957, cost=19.94, duration_ms=1_816_000),
               ("AssistantMessage", {}),
               _result(2, 528, cost=20.18, duration_ms=30_000)])
    got = trace.totals(t)
    assert got["num_turns"] == 164
    assert got["usage"]["output_tokens"] == 104_485
    assert got["usage"]["cache_read_input_tokens"] == 10
    assert got["agent_duration_ms"] == 1_846_000
    assert got["total_cost_usd"] == 20.18


def test_nested_usage_counters_accumulate_too(tmp_path):
    t = tmp_path / "trace.jsonl"
    _write(t, [("ResultMessage", {"usage": {"server_tool_use": {"requests": 3}}}),
               ("ResultMessage", {"usage": {"server_tool_use": {"requests": 4}}})])
    assert trace.totals(t)["usage"]["server_tool_use"]["requests"] == 7


def test_a_trace_cut_mid_run_says_so(tmp_path):
    t = tmp_path / "trace.jsonl"
    _write(t, [("AssistantMessage", {}), ("UserMessage", {})])
    t.write_text(t.read_text() + '{"type": "AssistantMessage", "mess')
    got = trace.totals(t)
    assert got["complete"] is False
    assert got["last_message"] == "UserMessage"  # the half line is not a message
    assert got["segments"] == 0


def test_walk_pairs_each_run_against_what_it_recorded(tmp_path):
    _write(tmp_path / "o02" / "trace.jsonl",
           [_result(162, 100, cost=1.0), _result(2, 5, cost=2.0)])
    (tmp_path / "o02" / "meta.json").write_text(json.dumps({"num_turns": 2}))
    _write(tmp_path / "o06" / "trace.jsonl", [("AssistantMessage", {})])
    (tmp_path / "o07").mkdir()

    rows = {r["run"]: r for r in trace.walk(tmp_path)}
    assert rows["o02"]["num_turns"] == 164 and rows["o02"]["recorded_num_turns"] == 2
    # died mid-agent: the trace stops, and there is no meta.json at all
    assert rows["o06"]["recorded_num_turns"] is None
    assert rows["o06"]["complete"] is False
    assert rows["o07"]["trace"] is None
