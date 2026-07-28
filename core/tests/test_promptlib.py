"""Prompts load from disk on every render — editing an md goes live."""

import pytest

from harness.promptlib import load_file, prompts


@pytest.fixture
def loader(tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "greet.md").write_text(
        "hello $name, escape $$DOLLAR\n", encoding="utf-8")
    return prompts(str(tmp_path / "module.py")), tmp_path


def test_interpolates_and_escapes(loader):
    prompt, _ = loader
    assert prompt("greet", name="run 7") == "hello run 7, escape $DOLLAR"


def test_no_values_returns_raw_text(loader):
    prompt, _ = loader
    assert "$name" in prompt("greet")  # no values -> no substitution pass


def test_missing_value_fails_loud(loader):
    prompt, _ = loader
    with pytest.raises(KeyError):
        prompt("greet", wrong="x")  # $name unfilled — substitute, not safe_


def test_rereads_from_disk_every_render(loader):
    prompt, root = loader
    assert "hello" in prompt("greet", name="x")
    (root / "prompts" / "greet.md").write_text("edited $name", encoding="utf-8")
    assert prompt("greet", name="x") == "edited x"  # no cache, no rebuild


def test_missing_prompt_file_raises(loader):
    prompt, _ = loader
    with pytest.raises(FileNotFoundError):
        prompt("nope")


def test_task_md_keeps_unknown_dollars(tmp_path):
    md = tmp_path / "task.md"
    md.write_text("run $run_id uses $DATABASE_URL", encoding="utf-8")
    # task files render with safe_substitute: env-style $VARS survive
    assert load_file(md, run_id="3") == "run 3 uses $DATABASE_URL"
