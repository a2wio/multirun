"""Prompts live in markdown next to the module that speaks them.
Python loads and interpolates; it never authors.

No cache, ever: the file is read again on every render, so editing a
prompt .md takes effect on the next run with no rebuild. Same contract
as everywhere else: writing a prompt inline in Python is a defect.
"""

from pathlib import Path
from string import Template


def prompts(module_file: str):
    """prompt = prompts(__file__)  ->  prompt("task_preamble", task=...)"""
    root = Path(module_file).resolve().parent / "prompts"

    def load(name: str, /, **values: object) -> str:
        text = (root / f"{name}.md").read_text(encoding="utf-8")
        if not values:
            return text.rstrip("\n")
        return Template(text).substitute(
            {k: str(v) for k, v in values.items()}).rstrip("\n")

    return load


def load_file(path: Path, /, **values: object) -> str:
    """Render an arbitrary markdown file (a task.md) the same way."""
    text = Path(path).read_text(encoding="utf-8")
    if not values:
        return text.rstrip("\n")
    return Template(text).safe_substitute(
        {k: str(v) for k, v in values.items()}).rstrip("\n")
