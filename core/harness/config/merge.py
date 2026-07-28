"""global + per-run overlay.

global: is defaults, each runs[] entry is a delta, per-run wins.
Mappings merge key-by-key, recursively; scalars and lists replace
whole. So a run that says `source: {ref: abc}` changes only the ref
and keeps the global repo — while `env:` lists replace outright,
because half-merged lists are how you get a run you can't explain.
"""


def deep_merge(base: dict, override: dict) -> dict:
    """Pure: neither input is mutated."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def merge_run(glob: dict, run_entry: dict) -> dict:
    """The merged view one run gets: global defaults + its own delta.

    Keys that don't belong on a run (fan-out-level knobs) are dropped
    from the base before merging so they never leak into a RunSpec.
    """
    base = {k: v for k, v in glob.items() if k not in ("name", "max_parallel")}
    return deep_merge(base, run_entry)
