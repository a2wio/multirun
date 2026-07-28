"""The merged config shape and its validation.

One YAML defines a fan-out: `global:` is defaults, `runs:` is a list of
deltas, per-run wins on merge (merge.py). What comes out is one
FanoutConfig holding N RunSpecs — each RunSpec is the complete,
self-contained answer to "what exactly did run 7 get?".

Validation is strict on purpose: unknown keys are rejected by name so a
typo fails at submit, not three branches deep into a fan-out.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .merge import merge_run


class ConfigError(Exception):
    pass


# keys allowed under global:. max_parallel is global-only: it guards one
# shared subscription, so a single run has no business raising it.
GLOBAL_KEYS = {"name", "source", "task", "model", "timeout", "max_parallel",
               "neon", "artifacts", "env"}
RUN_KEYS = (GLOBAL_KEYS - {"name", "max_parallel"}) | {"id", "dotenv"}
SOURCE_KEYS = {"repo", "ref", "seed"}
NEON_KEYS = {"project", "parent_branch", "database", "role"}

_TIMEOUT_RE = re.compile(r"^(\d+)\s*(s|m|h)?$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
# run ids become branch names, job names, artifact paths — keep them tame
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,15}$")


def parse_timeout(value: object) -> int:
    """'30m' / '2h' / '90s' / bare seconds -> seconds."""
    if isinstance(value, int) and not isinstance(value, bool):
        if value <= 0:
            raise ConfigError(f"timeout must be positive, got {value}")
        return value
    m = _TIMEOUT_RE.match(str(value).strip())
    if not m:
        raise ConfigError(f"can't parse timeout {value!r} (want e.g. 30m, 2h, 90s)")
    n, unit = int(m.group(1)), m.group(2) or "s"
    if n <= 0:
        raise ConfigError(f"timeout must be positive, got {value!r}")
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def _reject_unknown(mapping: dict, allowed: set, where: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ConfigError(f"unknown key(s) in {where}: {', '.join(sorted(unknown))}")


def _require_mapping(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigError(f"{where} must be a mapping, got {type(value).__name__}")
    return value


@dataclass(frozen=True)
class Source:
    repo: str
    ref: str
    seed: str | None = None  # dir of .sql fixtures, relative to the task dir

    @classmethod
    def parse(cls, raw: object, where: str) -> "Source":
        raw = _require_mapping(raw, where)
        _reject_unknown(raw, SOURCE_KEYS, where)
        repo, ref = raw.get("repo"), raw.get("ref")
        if not repo:
            raise ConfigError(f"{where}.repo is required")
        if not ref or not _SHA_RE.match(str(ref).lower()):
            raise ConfigError(
                f"{where}.ref must be a commit sha (7-40 hex chars), got {ref!r} — "
                "runs are only comparable if they all start from the same commit")
        return cls(repo=str(repo), ref=str(ref).lower(), seed=raw.get("seed"))


@dataclass(frozen=True)
class NeonCfg:
    project: str
    parent_branch: str | None = None  # name or id; None = the project's default
    database: str = "neondb"
    role: str = "neondb_owner"

    @classmethod
    def parse(cls, raw: object, where: str) -> "NeonCfg":
        raw = _require_mapping(raw, where)
        _reject_unknown(raw, NEON_KEYS, where)
        if not raw.get("project"):
            raise ConfigError(f"{where}.project is required")
        return cls(project=str(raw["project"]),
                   parent_branch=raw.get("parent_branch"),
                   database=str(raw.get("database", "neondb")),
                   role=str(raw.get("role", "neondb_owner")))


@dataclass(frozen=True)
class RunSpec:
    """One run, fully merged. Everything the runner may see is here."""
    id: str
    source: Source
    task: str                 # path to the task dir, relative to the repo root
    model: str
    timeout_s: int
    neon: NeonCfg
    artifacts: str
    env: dict = field(default_factory=dict)
    dotenv: str | None = None

    @classmethod
    def parse(cls, merged: dict, where: str) -> "RunSpec":
        _reject_unknown(merged, RUN_KEYS, where)
        if merged.get("id") in (None, ""):
            raise ConfigError(f"{where}: every run needs an id")
        if not _ID_RE.match(str(merged["id"]).lower()):
            raise ConfigError(f"{where}: id {merged['id']!r} — ids become branch "
                              "and job names; use a-z, 0-9, - or _, max 16 chars")
        for key in ("source", "task", "model", "neon"):
            if key not in merged:
                raise ConfigError(f"{where}: {key!r} missing (set it in global: "
                                  "or on the run)")
        env = merged.get("env") or {}
        _require_mapping(env, f"{where}.env")
        return cls(id=str(merged["id"]),
                   source=Source.parse(merged["source"], f"{where}.source"),
                   task=str(merged["task"]),
                   model=str(merged["model"]),
                   timeout_s=parse_timeout(merged.get("timeout", "30m")),
                   neon=NeonCfg.parse(merged["neon"], f"{where}.neon"),
                   artifacts=str(merged.get("artifacts", "artifacts")),
                   env={str(k): str(v) for k, v in env.items()},
                   dotenv=merged.get("dotenv"))


@dataclass(frozen=True)
class FanoutConfig:
    name: str
    max_parallel: int
    runs: tuple[RunSpec, ...]
    raw: dict  # the yaml as loaded — stored verbatim with results


def load_config(path: str | Path) -> FanoutConfig:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"no such config: {path}") from None
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid yaml: {e}") from None
    return parse_config(_require_mapping(raw, str(path)), default_name=path.stem)


def parse_config(raw: dict, default_name: str = "fanout") -> FanoutConfig:
    _reject_unknown(raw, {"global", "runs"}, "top level")
    glob = _require_mapping(raw.get("global", {}), "global")
    _reject_unknown(glob, GLOBAL_KEYS, "global")

    runs_raw = raw.get("runs")
    if not isinstance(runs_raw, list) or not runs_raw:
        raise ConfigError("runs: must be a non-empty list")

    max_parallel = glob.get("max_parallel", 3)
    if not isinstance(max_parallel, int) or isinstance(max_parallel, bool) \
            or max_parallel < 1:
        raise ConfigError(f"global.max_parallel must be a positive int, "
                          f"got {max_parallel!r}")

    specs, seen = [], set()
    for i, entry in enumerate(runs_raw):
        where = f"runs[{i}]"
        entry = _require_mapping(entry, where)
        if "max_parallel" in entry:
            raise ConfigError(f"{where}: max_parallel is global-only — it guards "
                              "one shared subscription")
        merged = merge_run(glob, entry)
        spec = RunSpec.parse(merged, where)
        if spec.id in seen:
            raise ConfigError(f"duplicate run id {spec.id!r}")
        seen.add(spec.id)
        specs.append(spec)

    return FanoutConfig(name=str(glob.get("name", default_name)),
                        max_parallel=max_parallel,
                        runs=tuple(specs), raw=raw)
