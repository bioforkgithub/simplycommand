"""Tests for simplycommand. Python itself (sys.executable) is the program run, so the tests work everywhere."""

import json
import os
import sys
import time

import pytest

import simplycommand as scmd
from simplycommand import learn
from simplycommand._running import SETTINGS

PY = sys.executable


def python(code: str) -> scmd.Program:
    return scmd.program(PY, "-c", code)


@pytest.fixture(autouse=True)
def fresh_settings():
    yield
    scmd.stop_showing_commands()
    scmd.stop_log()


# ---------------------------------------------------------------- building commands
def test_options_become_words():
    prog = scmd.program("samtools").add_options(o="x.bam", threads=4, verbose=True, quiet=False, skip=None)
    assert prog.get_command_words() == ["samtools", "-o", "x.bam", "--threads", "4", "--verbose"]


def test_underscores_trailing_and_lists():
    prog = scmd.program("tool").add_options(min_length=10, in_="a.txt", I=["x", "y"])
    assert prog.get_command_words() == ["tool", "--min-length", "10", "--in", "a.txt", "-I", "x", "-I", "y"]


@pytest.mark.parametrize("style, expected", [
    ("-long_name", ["-max_target_seqs", "5"]),
    ("-long-name", ["-max-target-seqs", "5"]),
    ("--long_name", ["--max_target_seqs", "5"]),
    ("--long-name=value", ["--max-target-seqs=5"]),
    ("/name", ["/max-target-seqs", "5"]),
])
def test_option_styles(style, expected):
    assert scmd.program("t", option_style=style).get_command_words(max_target_seqs=5)[1:] == expected


def test_one_letter_never_gets_equals_in_double_dash_style():
    assert scmd.program("t", option_style="--long-name=value").get_command_words(o="x")[1:] == ["-o", "x"]


def test_unknown_style_is_explained():
    with pytest.raises(scmd.SimplyCommandError, match="option_style"):
        scmd.program("t", option_style="long")


def test_add_option_switch_words_and_full_names():
    prog = (scmd.program("t").add_words("sort", "in.bam").add_option("--in", "x")
            .add_option("files", "a", "b").add_switch("v", "force"))
    assert prog.get_command_words() == ["t", "sort", "in.bam", "--in", "x", "--files", "a", "b", "-v", "--force"]


def test_add_option_without_value_points_to_switch():
    with pytest.raises(scmd.SimplyCommandError, match="add_switch"):
        scmd.program("t").add_option("verbose")


def test_remove_undo_and_copy():
    prog = scmd.program("t").add_option("threads", 4).add_option("o", "x")
    prog.remove_option("threads")
    assert prog.get_command_words() == ["t", "-o", "x"]
    prog.undo()
    assert prog.get_command_words() == ["t", "--threads", "4", "-o", "x"]
    other = prog.copy().add_words("more")
    assert prog.get_command_words() == ["t", "--threads", "4", "-o", "x"]
    assert other.get_command_words()[-1] == "more"
    with pytest.raises(scmd.SimplyCommandError, match="Did you mean"):
        prog.remove_option("thread")


def test_undo_with_nothing_to_undo():
    with pytest.raises(scmd.SimplyCommandError, match="nothing to undo"):
        scmd.program("t").undo()


def test_subcommands_by_attribute():
    git = scmd.program("git")
    assert git.cherry_pick.get_command_words("abc") == ["git", "cherry-pick", "abc"]
    assert git.remote.add.get_command_words("origin") == ["git", "remote", "add", "origin"]
    assert git.get_command_words() == ["git"]  # git itself is unchanged
    assert git.make_subcommand("import").get_command_words() == ["git", "import"]


def test_typo_of_own_word_is_not_a_subcommand():
    with pytest.raises(AttributeError, match="show_command"):
        scmd.program("git").show_comand


def test_command_line_is_quoted():
    line = scmd.program("t", "a file.txt").get_command_line()
    assert '"a file.txt"' in line or "'a file.txt'" in line


def test_show_command(capsys):
    scmd.program("t").add_option("o", "x").show_command()
    assert capsys.readouterr().out.strip() == "t -o x"


# ---------------------------------------------------------------- running
def test_run_and_result():
    result = python("print('hello'); print('world')").run()
    assert result.worked and bool(result) and result.exit_code == 0
    assert result.output == "hello\nworld\n" and str(result) == result.output
    assert result.get_output_lines() == ["hello", "world"]
    assert "worked" in repr(result) and "2 lines" in repr(result)


def test_calling_a_program_runs_it():
    assert scmd.program(PY)("-c", "print(5)").output.strip() == "5"


def test_failure_raises_with_last_lines():
    with pytest.raises(scmd.CommandFailedError) as caught:
        python("import sys; sys.stderr.write('bad input\\n'); sys.exit(3)").run()
    assert "exit code 3" in str(caught.value) and "bad input" in str(caught.value)
    assert caught.value.result.exit_code == 3


def test_keep_going_if_it_fails():
    result = python("import sys; sys.exit(2)").keep_going_if_it_fails().run()
    assert not result.worked and result.exit_code == 2 and "failed" in result.describe(quiet=True)


def test_program_not_found():
    with pytest.raises(scmd.ProgramNotFoundError, match="was not found"):
        scmd.program("surely-no-such-program-xyz").run()
    assert not scmd.program("surely-no-such-program-xyz").is_installed()
    assert scmd.program(PY).is_installed()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows advice")
def test_linux_word_on_windows_gets_advice():
    if scmd.program("ls").is_installed():
        pytest.skip("ls is installed here")
    with pytest.raises(scmd.ProgramNotFoundError, match="dir"):
        scmd.program("ls").run()


def test_input_text_and_input_file(tmp_path):
    upper = python("import sys; print(sys.stdin.read().upper(), end='')")
    assert upper.copy().use_input_text("acgt").run().output == "ACGT"
    file = tmp_path / "in.txt"
    file.write_text("ttt")
    assert upper.copy().use_input_file(file).run().output == "TTT"


def test_save_output_and_errors_to(tmp_path):
    out, err = tmp_path / "sub" / "out.txt", tmp_path / "err.txt"
    result = python("import sys; print('data'); sys.stderr.write('log')").save_output_to(out).save_errors_to(err).run()
    assert out.read_text().strip() == "data" and err.read_text() == "log"
    assert result.output == "" and str(out) in repr(result)
    python("print('more')").save_output_to(out, add_to_end=True).run()
    assert out.read_text().split() == ["data", "more"]


def test_folder_and_environment(tmp_path):
    result = python("import os; print(os.getcwd()); print(os.environ['SC_TEST'])") \
        .set_folder(tmp_path).set_environment(SC_TEST=42).run()
    folder, value = result.get_output_lines()
    assert os.path.samefile(folder, tmp_path) and value == "42"


def test_missing_folder_is_explained(tmp_path):
    with pytest.raises(scmd.SimplyCommandError, match="does not exist"):
        python("pass").set_folder(tmp_path / "nope").run()


def test_time_limit():
    with pytest.raises(scmd.TimeLimitError) as caught:
        python("import time; print('start', flush=True); time.sleep(30)").set_time_limit(1).run()
    assert caught.value.result.stopped == "time limit"
    assert caught.value.result.seconds < 10


def test_live_output_is_kept_too(capfd):
    result = python("print('live line')").show_output_while_running().run()
    assert "live line" in capfd.readouterr().out and result.output.strip() == "live line"


def test_pipeline():
    pipe = python("print('a'); print('b')") | python("import sys; print(sys.stdin.read().upper(), end='')")
    assert isinstance(pipe, scmd.Pipeline) and " | " in pipe.get_command_line()
    assert pipe.run().output == "A\nB\n"
    three = pipe | python("import sys; print(len(sys.stdin.read().split()))")
    assert len(three.get_programs()) == 3 and three.run().output.strip() == "2"


def test_pipeline_failure_in_the_middle():
    # the middle program reads everything first, so the first one never meets a closed pipe
    pipe = python("print('x')") | python("import sys; sys.stdin.read(); sys.exit(4)") | python("print('end')")
    result = pipe.keep_going_if_it_fails().run()
    assert not result.worked and result.exit_codes == [0, 4, 0]


def test_background_and_stop():
    job = python("import time; time.sleep(0.5); print('done')").start_in_background()
    assert job.is_running()
    assert job.wait_until_done().output.strip() == "done" and not job.is_running()
    slow = python("import time; time.sleep(30)").start_in_background()
    result = slow.stop()
    assert result.stopped == "by you" and not result.worked


def test_run_together_keeps_order_and_runs_at_once():
    jobs = [python(f"import time; time.sleep(0.6); print({i})") for i in range(4)]
    start = time.perf_counter()
    results = scmd.run_together(jobs, at_most=4)
    assert [r.output.strip() for r in results] == ["0", "1", "2", "3"]
    assert time.perf_counter() - start < 2.2


def test_run_line_and_run_in_shell():
    assert scmd.run_line(f'"{PY}" -c "print(7)"').output.strip() == "7"
    assert scmd.run_in_shell("echo hello").output.strip().strip('"') == "hello"


def test_utf8_output():
    assert python("import sys; sys.stdout.buffer.write('blå ß'.encode())").run().output == "blå ß"


# ---------------------------------------------------------------- results
def test_result_rows_json_and_find():
    rows = python("print('# comment'); print('a\\t1'); print('b\\t2')").run()
    assert rows.get_output_as_rows() == [["a", "1"], ["b", "2"]]
    assert rows.find_lines_with("B", ignore_case=True) == ["b\t2"]
    data = python("import json; print(json.dumps({'n': 3}))").run()
    assert data.get_output_as_json() == {"n": 3}
    with pytest.raises(scmd.SimplyCommandError, match="not JSON"):
        rows.get_output_as_json()


def test_result_save_and_typo(tmp_path):
    result = python("print('x')").run()
    result.save_output(tmp_path / "o.txt")
    assert (tmp_path / "o.txt").read_text().strip() == "x"
    with pytest.raises(AttributeError, match="show_output"):
        result.show_outptu()


# ---------------------------------------------------------------- record keeping
def test_log_and_show_commands(tmp_path, capsys):
    log = tmp_path / "commands.log"
    scmd.start_log_in(log)
    scmd.start_showing_commands()
    python("print(1)").run()
    assert capsys.readouterr().out.startswith("> ")
    text = log.read_text(encoding="utf-8")
    assert "worked" in text and "print(1)" in text
    scmd.stop_log()
    assert SETTINGS["log_file"] is None


# ---------------------------------------------------------------- wrapping a tool in a class
def test_program_subclass():
    class Python(scmd.Program):
        program_name = PY

        def add_up(self, a, b):
            return int(self.run("-c", f"print({a} + {b})").output)

    assert Python().add_up(2, 3) == 5


# ---------------------------------------------------------------- own command-line programs
class Seqs(scmd.CommandLineProgram):
    """Small tools for sequences."""

    def count(self, text: str, min_length: int = 0, upper: bool = False):
        """Count the words.
        text: the words to count
        min_length: only words at least this long
        """
        words = [w for w in text.split(",") if len(w) >= min_length]
        return len(words) if not upper else f"{len(words)} WORDS"

    def join_all(self, parts: list[str], keep: bool = True, sep: str = "-"):
        """Join the parts."""
        return sep.join(parts) if keep else ""


def test_command_line_program(capsys):
    assert Seqs().start_from_command_line(["count", "a,bb,ccc", "--min-length", "2"]) == 2
    assert Seqs().start_from_command_line(["count", "a,bb", "--upper"]) == "2 WORDS"
    assert Seqs().start_from_command_line(["join-all", "x", "y", "--sep", "+"]) == "x+y"
    assert Seqs().start_from_command_line(["join_all", "x", "--no-keep"]) == ""
    assert Seqs().get_commands() == ["count", "join-all"]
    assert "2" in capsys.readouterr().out


def test_command_line_program_help(capsys):
    with pytest.raises(SystemExit):
        Seqs().start_from_command_line(["--help"])
    out = capsys.readouterr().out
    assert "Small tools for sequences." in out and "join-all" in out
    with pytest.raises(SystemExit):
        Seqs().start_from_command_line(["count", "--help"])
    assert "only words at least this long" in capsys.readouterr().out


def test_make_command_line_program_from_function():
    def resize(image: str, width: int = 800, keep_ratio: bool = True):
        """Resize an image."""
        return f"{image} {width} {keep_ratio}"

    assert scmd.make_command_line_program(resize, ["a.png", "--width", "10", "--no-keep-ratio"]) == "a.png 10 False"


def test_plain_class_works_too():
    class Tools:
        def double(self, n: int):
            return n * 2

    assert scmd.make_command_line_program(Tools, ["5"]) == 10


def test_friendly_error_inside_command(capsys):
    class Breaks(scmd.CommandLineProgram):
        def go(self):
            raise scmd.SimplyCommandError("The file is empty.")

    with pytest.raises(SystemExit):
        Breaks().start_from_command_line([])
    assert "Error: The file is empty." in capsys.readouterr().err


# ---------------------------------------------------------------- learning
def test_every_public_word_is_in_a_group():
    grouped = {name for _, names in learn.GROUPS for name in names}
    owners = learn._owners()
    for prefix in ("program", "result", "running", "pipeline"):
        cls = owners[prefix]
        for word in dir(cls):
            if word.startswith("_"):
                continue
            if prefix == "pipeline" and f"program.{word}" in grouped:
                continue
            if prefix == "program" and word in ("name", "program_name", "option_style"):
                continue
            if prefix == "result" and word in ("command_line", "exit_codes", "folder", "output_file", "stopped"):
                continue
            assert f"{prefix}.{word}" in grouped, f"{prefix}.{word} is not in learn.GROUPS"
    for word in scmd.__all__:
        if word[0].islower():
            assert f"scmd.{word}" in grouped, f"scmd.{word} is not in learn.GROUPS"


def test_every_grouped_word_has_a_description():
    for _, names in learn.GROUPS:
        for full in names:
            _, thing = learn._find(full)
            assert learn._doc(full, thing), f"{full} has no description"


def test_help_and_lessons(capsys):
    scmd.show_all_words()
    scmd.help("add_option")
    scmd.help("result.worked")
    scmd.show_lesson()
    for n in range(1, len(learn.LESSONS) + 1):
        scmd.show_lesson(n)
    out = capsys.readouterr().out
    assert "program.add_option(name, *values)" in out and "Lesson 7" in out
    with pytest.raises(scmd.SimplyCommandError, match="Did you mean"):
        scmd.help("add_optoin")


def test_missing_module_word():
    with pytest.raises(AttributeError, match="scmd.run_line"):
        scmd.run_lines
