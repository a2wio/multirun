"""The config layer: shape, validation, and who wins on merge."""

import pytest

from harness.config.merge import deep_merge, merge_run
from harness.config.schema import ConfigError, parse_config, parse_timeout

GLOBAL = {
    "source": {"repo": "git@github.com:kubeden/app.git", "ref": "a" * 40},
    "task": "tasks/add-teams",
    "model": "sonnet",
    "timeout": "30m",
    "neon": {"project": "proj-123"},
}


def cfg(runs, glob=None):
    return parse_config({"global": {**GLOBAL, **(glob or {})}, "runs": runs})


# -- merge semantics ----------------------------------------------------------

def test_per_run_wins_on_scalars():
    c = cfg([{"id": "1"}, {"id": "2", "model": "opus"}])
    assert c.runs[0].model == "sonnet"
    assert c.runs[1].model == "opus"


def test_mappings_merge_key_by_key():
    c = cfg([{"id": "1", "source": {"ref": "b" * 40}}])
    assert c.runs[0].source.ref == "b" * 40
    assert c.runs[0].source.repo == GLOBAL["source"]["repo"]  # kept from global


def test_deep_merge_is_pure():
    base, override = {"a": {"b": 1}}, {"a": {"c": 2}}
    out = deep_merge(base, override)
    assert out == {"a": {"b": 1, "c": 2}}
    assert base == {"a": {"b": 1}} and override == {"a": {"c": 2}}


def test_lists_replace_whole():
    assert deep_merge({"x": [1, 2]}, {"x": [3]}) == {"x": [3]}


def test_env_merges_recursively():
    c = cfg([{"id": "1", "env": {"B": "2"}}], glob={"env": {"A": "1"}})
    assert c.runs[0].env == {"A": "1", "B": "2"}


def test_fanout_only_keys_never_reach_a_run():
    merged = merge_run({**GLOBAL, "name": "x", "max_parallel": 5}, {"id": "1"})
    assert "name" not in merged and "max_parallel" not in merged


# -- validation ---------------------------------------------------------------

def test_unknown_key_named_in_error():
    with pytest.raises(ConfigError, match="modle"):
        cfg([{"id": "1", "modle": "opus"}])


def test_unknown_global_key_rejected():
    with pytest.raises(ConfigError, match="global"):
        parse_config({"global": {**GLOBAL, "paralel": 2}, "runs": [{"id": "1"}]})


def test_runs_must_be_nonempty():
    with pytest.raises(ConfigError, match="non-empty"):
        parse_config({"global": GLOBAL, "runs": []})


def test_duplicate_ids_rejected():
    with pytest.raises(ConfigError, match="duplicate"):
        cfg([{"id": "1"}, {"id": "1"}])


def test_id_shape_enforced():
    with pytest.raises(ConfigError, match="branch"):
        cfg([{"id": "run one!"}])


def test_max_parallel_is_global_only():
    with pytest.raises(ConfigError, match="global-only"):
        cfg([{"id": "1", "max_parallel": 10}])


def test_ref_must_be_a_sha():
    with pytest.raises(ConfigError, match="sha"):
        cfg([{"id": "1", "source": {"ref": "main"}}])


def test_missing_required_key_points_at_it():
    raw = {k: v for k, v in GLOBAL.items() if k != "neon"}
    with pytest.raises(ConfigError, match="neon"):
        parse_config({"global": raw, "runs": [{"id": "1"}]})


def test_neon_project_required():
    raw = {k: v for k, v in GLOBAL.items() if k != "neon"}
    with pytest.raises(ConfigError, match="project"):
        parse_config({"global": raw,
                      "runs": [{"id": "1", "neon": {"parent_branch": "x"}}]})


def test_neon_map_merges_so_partial_override_keeps_project():
    c = cfg([{"id": "1", "neon": {"parent_branch": "x"}}])
    assert c.runs[0].neon.project == "proj-123"
    assert c.runs[0].neon.parent_branch == "x"


def test_bad_yaml_types_rejected():
    with pytest.raises(ConfigError, match="mapping"):
        parse_config({"global": GLOBAL, "runs": ["not-a-mapping"]})


# -- timeout parsing ----------------------------------------------------------

@pytest.mark.parametrize("raw,expect", [
    ("30m", 1800), ("2h", 7200), ("90s", 90), (45, 45), ("45", 45),
])
def test_timeout_forms(raw, expect):
    assert parse_timeout(raw) == expect


@pytest.mark.parametrize("bad", ["", "soon", "-5m", 0, "0", True])
def test_timeout_garbage(bad):
    with pytest.raises(ConfigError):
        parse_timeout(bad)


def test_defaults():
    c = cfg([{"id": "1"}])
    assert c.max_parallel == 3
    assert c.runs[0].timeout_s == 1800
    assert c.runs[0].neon.database == "neondb"
