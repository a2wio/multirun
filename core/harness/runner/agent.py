"""The Agent SDK invocation — and nothing else.

The agent runs through Anthropic's Agent SDK (headless Claude Code) on
subscription auth: the CLI's own OAuth credentials, mounted into the
pod as a Secret, or already on disk locally. There is deliberately no
ANTHROPIC_API_KEY path — ten model-runs through the api is money, the
subscription is flat — so the variable is stripped from the child
environment to make the wrong path impossible, not just discouraged.

Every message is appended to trace.jsonl as it streams; the trace is an
artifact, not a debugging afterthought.
"""

import asyncio
import dataclasses
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentResult:
    is_error: bool
    exit_reason: str          # done | timeout | error
    result_text: str
    num_turns: int
    duration_ms: int
    session_id: str | None
    usage: dict
    total_cost_usd: float | None


def _jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return repr(obj)


def run_task(prompt: str, *, workdir: Path, model: str, timeout_s: int,
             trace_path: Path, extra_env: dict | None = None) -> AgentResult:
    return asyncio.run(_run(prompt, workdir=workdir, model=model,
                            timeout_s=timeout_s, trace_path=trace_path,
                            extra_env=extra_env or {}))


async def _run(prompt: str, *, workdir: Path, model: str, timeout_s: int,
               trace_path: Path, extra_env: dict) -> AgentResult:
    from claude_agent_sdk import ClaudeAgentOptions, query

    os.environ.pop("ANTHROPIC_API_KEY", None)  # subscription auth only
    env = {k: v for k, v in extra_env.items() if v is not None}

    options = ClaudeAgentOptions(
        cwd=str(workdir),
        model=model,
        permission_mode="bypassPermissions",  # the whole workspace is disposable
        setting_sources=[],  # no user/project settings bleed into a run
        env=env,
    )

    started = time.monotonic()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    result_msg = None

    async def consume():
        nonlocal result_msg
        with trace_path.open("a", encoding="utf-8") as trace:
            async for message in query(prompt=prompt, options=options):
                trace.write(json.dumps({"type": type(message).__name__,
                                        "message": _jsonable(message)}) + "\n")
                trace.flush()
                if type(message).__name__ == "ResultMessage":
                    result_msg = message

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    except TimeoutError:
        return AgentResult(is_error=True, exit_reason="timeout", result_text="",
                           num_turns=0,
                           duration_ms=int((time.monotonic() - started) * 1000),
                           session_id=None, usage={}, total_cost_usd=None)

    if result_msg is None:
        return AgentResult(is_error=True, exit_reason="error",
                           result_text="agent ended without a result message",
                           num_turns=0,
                           duration_ms=int((time.monotonic() - started) * 1000),
                           session_id=None, usage={}, total_cost_usd=None)

    is_error = bool(getattr(result_msg, "is_error", False))
    return AgentResult(
        is_error=is_error,
        exit_reason="error" if is_error else "done",
        result_text=getattr(result_msg, "result", "") or "",
        num_turns=int(getattr(result_msg, "num_turns", 0) or 0),
        duration_ms=int(getattr(result_msg, "duration_ms", 0)
                        or (time.monotonic() - started) * 1000),
        session_id=getattr(result_msg, "session_id", None),
        usage=_jsonable(getattr(result_msg, "usage", {}) or {}),
        total_cost_usd=getattr(result_msg, "total_cost_usd", None),
    )
