"""Every example runs, so the examples can never go out of date without a test failing."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SCRIPTS = sorted(EXAMPLES.glob("0*.py"))


def run(script: str, *words: str, cwd=None, text_in: str | None = None):
    result = subprocess.run([sys.executable, str(EXAMPLES / script), *words], capture_output=True, text=True,
                            cwd=cwd, input=text_in, timeout=60)
    return result


@pytest.mark.parametrize("script", [s.name for s in SCRIPTS])
def test_every_example_has_help(script):
    result = run(script, "--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout


def test_hello():
    assert run("01_hello.py", "Ann", "-t", "2", "--shout").stdout.split("\n")[:2] == ["HELLO, ANN!"] * 2


def test_kinds_of_options(tmp_path):
    text = tmp_path / "words.txt"
    text.write_text("the cat and The dog and the bird")
    result = run("02_kinds_of_options.py", str(text), "-i", "--top", "1", "--no-numbers")
    assert result.stdout.strip() == "the"
    bad = run("02_kinds_of_options.py", str(tmp_path / "missing.txt"))
    assert bad.returncode == 1 and "is not a file" in bad.stderr and "Traceback" not in bad.stderr
    choice = run("02_kinds_of_options.py", str(text), "--sort", "size")
    assert choice.returncode == 2 and "invalid choice" in choice.stderr


def test_several_commands(tmp_path):
    todo = ["--list-file", str(tmp_path / "todo.json")]
    assert "Added task 1" in run("03_several_commands.py", *todo, "add", "Buy milk").stdout
    run("03_several_commands.py", *todo, "add", "Write report", "--important")
    run("03_several_commands.py", *todo, "done", "1")
    assert run("03_several_commands.py", *todo, "show").stdout.strip() == "[ ] 2. Write report (!)"
    assert "[x] 1. Buy milk" in run("03_several_commands.py", *todo, "show", "--all").stdout
    assert "no task 9" in run("03_several_commands.py", *todo, "done", "9").stderr
    assert "Nothing was removed" in run("03_several_commands.py", *todo, "clear", text_in="n\n").stdout
    assert "empty" in run("03_several_commands.py", *todo, "clear", "--yes").stdout
    assert run("03_several_commands.py", "--version").stdout.strip() == "1.0"


def test_groups_and_settings(tmp_path, monkeypatch):
    for name, size in (("a.txt", 10), ("b.txt", 300), ("c.txt", 20)):
        (tmp_path / name).write_text("x" * size)
    biggest = run("04_groups_and_settings.py", "folder", "biggest", str(tmp_path), "-n", "1")
    assert "b.txt" in biggest.stdout and "a.txt" not in biggest.stdout
    info = run("04_groups_and_settings.py", "computer", "info", "--as-json")
    assert "python" in json.loads(info.stdout)
    both = run("04_groups_and_settings.py", "computer", "info", "--as-json", "--as-table")
    assert both.returncode == 2 and "not allowed with" in both.stderr
    has = run("04_groups_and_settings.py", "computer", "has", Path(sys.executable).stem, "surely-not-a-program")
    assert has.stdout.split()[-1] == "no"


def test_groups_read_the_environment(tmp_path, monkeypatch):
    for i in range(4):
        (tmp_path / f"f{i}.txt").write_text("x" * (i + 1))
    monkeypatch.setenv("HELPER_HOW_MANY", "2")
    assert len(run("04_groups_and_settings.py", "folder", "biggest", str(tmp_path)).stdout.splitlines()) == 2


def test_talking_without_a_person():
    result = run("05_talking_to_people.py", "--name", "Ann", "--language", "Norwegian", "--yes", "--steps", "3")
    assert result.returncode == 0 and "Velkommen, Ann!" in result.stdout


def test_talking_with_a_person():
    result = run("05_talking_to_people.py", "--steps", "2", text_in="Ann\n2\ny\n")
    assert "Velkommen, Ann!" in result.stdout


def test_running_other_programs(tmp_path):
    py = sys.executable
    versions = run("06_running_other_programs.py", "versions", py, "surely-not-a-program")
    assert "Python" in versions.stdout and "not installed" in versions.stdout
    log = tmp_path / "runs.log"
    timed = run("06_running_other_programs.py", "timed", "--log", str(log), "--", py, "-c", "print(6 * 7)")
    assert "42" in timed.stdout and "worked" in timed.stdout and "print(6 * 7)" in log.read_text()
    lines = run("06_running_other_programs.py", "count-lines", "--", py, "-c", "print(1); print(2); print(3)")
    assert lines.stdout.strip() == "3 lines"
    together = run("06_running_other_programs.py", "together", "--how-many", "2")
    assert together.stdout.count("done") == 2
