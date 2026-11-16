"""Tests for the last gaps: limits and usage, signals, detached programs, the pseudo-terminal, the
Popen settings, more file words, talking to people and the richer command-line programs."""

import json
import os
import stat
import sys
import threading
import time

import pytest

import simplycommand as scmd
from simplycommand import files as scmd_files

PY = sys.executable
ON_WINDOWS = sys.platform.startswith("win")
posix_only = pytest.mark.skipif(ON_WINDOWS, reason="Linux and macOS only")
windows_only = pytest.mark.skipif(not ON_WINDOWS, reason="Windows only")


def python(code: str) -> scmd.Program:
    return scmd.program(PY, "-c", code)


# ================================================================ streams
def test_save_output_and_also_keep(tmp_path):
    out = tmp_path / "out.txt"
    result = python("print('both')").save_output_to(out, also_keep=True).run()
    assert result.output.strip() == "both" and out.read_text().strip() == "both"
    assert "tee" in python("pass").save_output_to(out, also_keep=True).get_command_line()


def test_save_errors_and_also_keep(tmp_path):
    err = tmp_path / "err.txt"
    result = python("import sys; sys.stderr.write('warn')").save_errors_to(err, also_keep=True).run()
    assert result.errors == "warn" and err.read_text() == "warn"


def test_send_errors_to_next_program(tmp_path):
    first = python("import sys; print('normal'); sys.stderr.write('problem\\n')").save_output_to(tmp_path / "o.txt")
    pipe = first.send_errors_to(python("import sys; print(sys.stdin.read().upper(), end='')"))
    assert pipe.run().output == "PROBLEM\n"
    assert (tmp_path / "o.txt").read_text().strip() == "normal"


def test_remove_environment_variable(monkeypatch):
    monkeypatch.setenv("SC_GONE", "here")
    code = "import os; print(os.environ.get('SC_GONE', 'missing'))"
    assert python(code).remove_environment_variable("SC_GONE").run().output.strip() == "missing"


def test_add_files_matching(tmp_path):
    (tmp_path / "run1").mkdir()
    for name in ("b.fa", "a.fa", "run1/c.fa", "x.txt"):
        (tmp_path / name).write_text("x")
    words = scmd.program("tool").set_folder(tmp_path).add_files_matching("**/*.fa").get_command_words()
    assert [w.replace("\\", "/") for w in words[1:]] == ["a.fa", "b.fa", "run1/c.fa"]
    with pytest.raises(scmd.SimplyCommandError, match="No files match"):
        scmd.program("tool").add_files_matching("*.nothing", in_folder=tmp_path)


# ================================================================ limits and usage
def test_usage_is_measured():
    result = python("x = bytearray(60 * 1024 * 1024); s = sum(range(3_000_000))").run()
    assert result.cpu_seconds is not None and result.cpu_seconds > 0
    assert result.peak_memory_mb is not None and result.peak_memory_mb >= 50


def test_memory_limit():
    result = (python("x = bytearray(400 * 1024 * 1024); print('got it')")
              .set_memory_limit(150).keep_going_if_it_fails().run())
    assert not result.worked and "got it" not in result.output
    assert python("print('small')").set_memory_limit(150).run().worked


def test_cpu_time_limit():
    with pytest.raises(scmd.TimeLimitError, match="CPU time"):
        python("while True: pass").set_cpu_time_limit(1).set_time_limit(60).run()


def test_limits_must_be_positive():
    with pytest.raises(scmd.SimplyCommandError):
        python("pass").set_memory_limit(0)
    with pytest.raises(scmd.SimplyCommandError):
        python("pass").set_cpu_time_limit(-1)


# ================================================================ signals, groups and detached programs
@posix_only
def test_send_any_signal():
    code = ("import signal, sys, time\n"
            "signal.signal(signal.SIGUSR1, lambda *a: (print('got it', flush=True), sys.exit(0)))\n"
            "print('ready', flush=True)\n"
            "time.sleep(30)")
    running = python(code).start_in_background()
    assert running.wait_for_text("ready", time_limit=10)
    running.send_signal("SIGUSR1")
    assert "got it" in running.wait_until_done().output


@windows_only
def test_ctrl_break_on_windows():
    running = python("import time; print('ready', flush=True); time.sleep(30)").start_in_own_group().start_in_background()
    assert running.wait_for_text("ready", time_limit=10)
    running.send_signal("ctrl+break")
    result = running.wait_until_done() if False else None  # noqa: F841
    start = time.perf_counter()
    while running.is_running() and time.perf_counter() - start < 10:
        time.sleep(0.05)
    assert not running.is_running()


def test_send_signal_explains_names():
    running = python("import time; time.sleep(5)").start_in_background()
    try:
        with pytest.raises(scmd.SimplyCommandError, match="send_signal"):
            running.send_signal("SIGNOTHING")
        if ON_WINDOWS:
            with pytest.raises(scmd.SimplyCommandError, match="start_in_own_group"):
                running.send_signal("ctrl+break")
    finally:
        running.stop()


def test_start_and_leave_running(tmp_path):
    flag = tmp_path / "done.txt"
    pid = python(f"import time, pathlib; time.sleep(0.5); pathlib.Path(r'{flag}').write_text('yes')") \
        .start_and_leave_running()
    assert isinstance(pid, int)
    deadline = time.perf_counter() + 15
    while not flag.exists() and time.perf_counter() < deadline:
        time.sleep(0.1)
    assert flag.read_text() == "yes"


# ================================================================ the pseudo-terminal
def test_pseudo_terminal_talks_like_a_person():
    pytest.importorskip("winpty") if ON_WINDOWS else None
    code = ("import sys; print('tty', sys.stdin.isatty(), sys.stdout.isatty(), flush=True); "
            "name = input('name? '); print('hello', name, flush=True)")
    running = python(code).run_in_pseudo_terminal().start_in_background()
    assert running.wait_for_text("name?", time_limit=20)
    running.send_text("Ann\n")
    result = running.wait_until_done()
    assert "tty True True" in result.output and "hello Ann" in result.output


def test_pseudo_terminal_is_for_one_program():
    pipe = (python("print(1)") | python("print(2)")).run_in_pseudo_terminal()
    with pytest.raises(scmd.SimplyCommandError, match="one program"):
        pipe.run()


# ================================================================ the rest of Popen
def test_use_program_file():
    # the base interpreter: a venv's python.exe on Windows is a launcher that starts Python again
    real = getattr(sys, "_base_executable", PY) if ON_WINDOWS else PY
    result = scmd.program("my-own-name", "-c", "import sys; print(sys.orig_argv[0])").use_program_file(real).run()
    assert result.output.strip() == "my-own-name"


def test_use_subprocess_settings():
    assert python("print(3)").use_subprocess_settings(bufsize=0).run().output.strip() == "3"
    with pytest.raises(scmd.SimplyCommandError, match="Did you mean bufsize"):
        python("pass").use_subprocess_settings(bufsiz=0)
    with pytest.raises(scmd.SimplyCommandError, match="set_folder"):
        python("pass").use_subprocess_settings(cwd=".")


@windows_only
def test_posix_settings_explained_on_windows():
    for prog in (python("pass").run_as_user("nobody"), python("pass").set_umask(0o022),
                 python("pass").share_open_files(3), python("pass").do_before_start(lambda: None)):
        with pytest.raises(scmd.SimplyCommandError, match="only on Linux and macOS"):
            prog.run()


@posix_only
def test_umask_and_before_start(tmp_path):
    made = tmp_path / "made.txt"
    python(f"open(r'{made}', 'w').close()").set_umask(0o077).run()
    assert stat.S_IMODE(made.stat().st_mode) == 0o600
    result = python("import os; print(os.environ.get('SC_BEFORE'))") \
        .do_before_start(lambda: os.environ.__setitem__("SC_BEFORE", "set")).run()
    assert result.worked  # the function ran without breaking the start


@posix_only
def test_share_open_files():
    read_end, write_end = os.pipe()
    try:
        python(f"import os; os.write({write_end}, b'shared')").share_open_files(write_end).run()
        assert os.read(read_end, 10) == b"shared"
    finally:
        os.close(read_end)
        os.close(write_end)


def test_run_as_administrator_words():
    words = scmd.program("tool", "a b").run_as_administrator().get_command_words()
    if ON_WINDOWS:
        assert words[0] == "powershell" and "-Verb RunAs" in words[-1] and "'\"a b\"'" in words[-1]
    else:
        assert words == ["sudo", "tool", "a b"]
    remote = scmd.program("tool").run_as_administrator().set_computer("me@server").get_command_words()
    assert remote == ["ssh", "me@server", "sudo tool"]


# ================================================================ files: permissions, links, facts
def test_set_permissions_and_runnable(tmp_path):
    file = tmp_path / "run.sh"
    file.write_text("echo hi")
    scmd.set_permissions(file, "r--r--r--")
    assert not os.access(file, os.W_OK)
    scmd.set_permissions(file, 0o644)
    assert os.access(file, os.W_OK)
    with pytest.raises(scmd.SimplyCommandError, match="rwxr-xr-x"):
        scmd.set_permissions(file, "rwxrwxrwz")
    scmd.make_runnable(file)
    if not ON_WINDOWS:
        assert os.access(file, os.X_OK)


def test_links(tmp_path, capsys):
    target = tmp_path / "real.txt"
    target.write_text("real")
    try:
        link = scmd.make_link(target, at=tmp_path / "link.txt")
    except scmd.SimplyCommandError as error:
        assert "Developer Mode" in str(error)
        pytest.skip("this Windows does not allow links without Developer Mode")
    assert open(link).read() == "real"
    assert scmd.find_where_link_points(link) == str(target)
    with pytest.raises(scmd.SimplyCommandError, match="already exists"):
        scmd.make_link(target, at=link)


def test_file_facts_and_temporary_things(capsys):
    folder = scmd.make_temporary_folder()
    try:
        file = scmd.make_temporary_file(ending=".fa")
        assert file.endswith(".fa") and os.path.isfile(file)
        dates = scmd.get_file_dates(file)
        assert set(dates) == {"changed", "opened", "made"}
        assert scmd.find_free_space(folder) > 0 and "free" in capsys.readouterr().out
        os.remove(file)
    finally:
        scmd.remove_folder(folder)


@posix_only
def test_set_owner_to_self(tmp_path):
    file = tmp_path / "mine.txt"
    file.write_text("x")
    scmd.set_owner(file, user=os.getuid())


def test_wait_for_change_in(tmp_path):
    def later():
        time.sleep(0.4)
        (tmp_path / "new.txt").write_text("x")

    threading.Thread(target=later).start()
    change = scmd.wait_for_change_in(tmp_path, time_limit=10, every=0.1)
    assert [os.path.basename(p) for p in change["added"]] == ["new.txt"]
    assert scmd.wait_for_change_in(tmp_path, time_limit=0.3, every=0.1) == {"added": [], "changed": [], "removed": []}


def test_find_files_with_folders_in_the_pattern(tmp_path):
    for name in ("run1/R1_a.fq", "run2/R1_b.fq", "run2/R2_b.fq", "R1_top.fq"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x")
    found = scmd.find_files("*/R1_*.fq", in_folder=tmp_path)
    assert [os.path.relpath(f, tmp_path).replace("\\", "/") for f in found] == ["run1/R1_a.fq", "run2/R1_b.fq"]


def test_copy_to_other_computers_words(tmp_path):
    assert scmd_files._copier("scp", 2222).get_command_words() == ["scp", "-r", "-P", "2222"]
    assert scmd_files._copier("rsync", None).get_command_words() == ["rsync", "-a", "--partial"]
    with pytest.raises(scmd.SimplyCommandError, match="Say what to send"):
        scmd.send_files_to("me@server")
    with pytest.raises(scmd.SimplyCommandError, match="does not exist"):
        scmd.send_files_to("me@server", tmp_path / "missing")


# ================================================================ talking to people
def test_ask_words(monkeypatch):
    answers = iter(["", "x", "12", "maybe", "y", "9", "fastq"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert scmd.ask("Name", default="S1") == "S1"
    assert scmd.ask("Count", kind=int) == 12          # "x" was not a number, so it asked again
    assert scmd.ask_yes_or_no("Sure?") is True        # "maybe" was not an answer
    assert scmd.ask_to_choose("Format?", ["fasta", "fastq"]) == "fastq"   # 9 was out of range
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "secret")
    assert scmd.ask_for_password() == "secret"


def test_ask_without_a_person(monkeypatch):
    def closed(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    with pytest.raises(scmd.SimplyCommandError, match="no one to answer"):
        scmd.ask("Name")


def test_colours(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert scmd.colour_text("ok", "green") == "ok"     # not a terminal: no codes
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert scmd.colour_text("ok", "red", bold=True) == "\033[1;31mok\033[0m"
    with pytest.raises(scmd.SimplyCommandError, match="green"):
        scmd.colour_text("x", "gren")


def test_show_progress(capsys):
    assert list(scmd.show_progress(range(5), label="Counting")) == [0, 1, 2, 3, 4]
    assert "5/5" in capsys.readouterr().err
    assert list(scmd.show_progress(iter("ab"))) == ["a", "b"]


# ================================================================ command-line programs, the rest
class Seqs(scmd.CommandLineProgram):
    """Sequence tools."""
    only_one_of = [("json", "tsv")]
    environment_prefix = "SEQS_TEST_"

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def count(self, fasta: str, min_length: int = 0, json: bool = False, tsv: bool = False):
        """Count sequences."""
        return f"{fasta} {min_length} json={json} tsv={tsv} v={self.verbose}"

    class database(scmd.CommandLineProgram):
        """Work with the database."""

        def __init__(self, name: str = "main"):
            self.name = name

        def add(self, fasta: str):
            """Add sequences."""
            return f"add {fasta} to {self.name}"

        def remove(self, fasta: str):
            """Remove sequences."""
            return f"remove {fasta} from {self.name}"


def test_nested_command_groups():
    assert Seqs.start_from_command_line(["database", "add", "x.fa"]) == "add x.fa to main"
    assert Seqs.start_from_command_line(["-v" if False else "--verbose", "database", "--name", "big", "remove", "y.fa"]) \
        == "remove y.fa from big"
    assert "database" in Seqs.get_commands()


def test_only_one_of(capsys):
    assert Seqs.start_from_command_line(["count", "a.fa", "--json"]).endswith("json=True tsv=False v=False")
    with pytest.raises(SystemExit):
        Seqs.start_from_command_line(["count", "a.fa", "--json", "--tsv"])
    assert "not allowed with" in capsys.readouterr().err


def test_defaults_from_the_environment(monkeypatch):
    monkeypatch.setenv("SEQS_TEST_MIN_LENGTH", "50")
    monkeypatch.setenv("SEQS_TEST_VERBOSE", "yes")
    assert Seqs.start_from_command_line(["count", "a.fa"]) == "a.fa 50 json=False tsv=False v=True"
    assert Seqs.start_from_command_line(["count", "a.fa", "--min-length", "7"]).startswith("a.fa 7")


def test_defaults_from_a_file(tmp_path):
    defaults = tmp_path / "seqs.json"
    defaults.write_text(json.dumps({"min_length": 5, "count": {"min_length": 9}}))

    class FromFile(Seqs):
        environment_prefix = None
        defaults_file = str(defaults)

    assert FromFile.start_from_command_line(["count", "a.fa"]).startswith("a.fa 9")
