"""One config -> N run plans.

A plan is a RunSpec plus every name derived from it: the fanout
instance, the k8s job, the configmap, the per-run secret, the Neon
branch, the artifact prefix. Deriving them all in one place, purely,
means a test can pin every name a fan-out will ever create — and the
reaper can recognize anything with our fingerprint on it.
"""

import re
import time
from dataclasses import dataclass

from ..config.schema import FanoutConfig, RunSpec
from ..resources.neon import RUN_PREFIX


def _slug(text: str, max_len: int = 40) -> str:
    """k8s-safe: lowercase alphanumerics and dashes, no edges."""
    out = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]+", "-", str(text).lower()))
    return out.strip("-")[:max_len].strip("-") or "x"


def instance_name(config_name: str, stamp: str | None = None) -> str:
    """Each submission of the same config is its own fanout instance."""
    return f"{_slug(config_name, 24)}-{stamp or time.strftime('%m%d%H%M')}"


@dataclass(frozen=True)
class RunPlan:
    fanout: str
    spec: RunSpec

    @property
    def slug(self) -> str:
        # same formula as RunHandle.slug: the branch a resource acquires
        # is the branch the reaper looks for
        return f"{self.fanout}-{self.spec.id}"

    @property
    def job_name(self) -> str:
        return f"mr-{self.slug}"[:63].rstrip("-")

    @property
    def configmap_name(self) -> str:
        return f"{self.job_name}-config"

    @property
    def secret_name(self) -> str:
        return f"{self.job_name}-secrets"

    @property
    def branch_name(self) -> str:
        return RUN_PREFIX + self.slug

    @property
    def artifact_prefix(self) -> str:
        return f"{self.fanout}/{self.spec.id}"


def plan(cfg: FanoutConfig, stamp: str | None = None) -> list[RunPlan]:
    fanout = instance_name(cfg.name, stamp)
    return [RunPlan(fanout=fanout, spec=spec) for spec in cfg.runs]
