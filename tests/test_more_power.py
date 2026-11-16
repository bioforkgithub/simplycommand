"""Tests for the full power: the rest of subprocess, other places to run, files and folders,
and the stronger command-line programs."""

import os
import sys
import time
from typing import Literal

import pytest

import simplycommand as scmd

PY = sys.executable
ON_WINDOWS = sys.platform.startswith("win")


def python(code: str) -> scmd.Program:
    return scmd.program(PY, "-c", code)


# ================================================================ the rest of subprocess
def test_accept_exit_codes():
    result = python("import sys; sys.exit(1)").accept_exit_codes(0, 1).run()
    assert result.worked and result.exit_code == 1
    with pytest.raises(scmd.CommandFailedError, match="accept_exit_codes"):
        python("import sys; sys.exit(1)").run()


def test_put_errors_into_output():
    result = python("import sys; print('out', flush=True); sys.stderr.write('err\\n')").put_errors_into_output().run()
    assert result.output.split() == ["out", "err"] and result.errors == ""
    assert "2>&1" in python("pass").put_errors_into_output().get_command_line()


def test_clean_environment(monkeypatch):
    monkeypatch.setenv("SC_SECRET", "x")
    code = "import os; print(os.environ.get('SC_SECRET', 'gone'), os.environ.get('SC_MINE'))"
    result = python(code).use_clean_environment().set_environment(SC_MINE="mine").run()
    assert result.output.split() == ["gone", "mine"]


def test_text_encoding_and_bytes():
    prog = python("import sys; sys.stdout.buffer.write('blå'.encode('latin-1'))")
    assert prog.copy().use_text_encoding("latin-1").run().output == "blå"
    assert prog.run().get_output_as_bytes() == "blå".encode("latin-1")
    with pytest.raises(LookupError):
        prog.use_text_encoding("no-such-encoding")


def test_do_with_each_line():
    seen, progress = [], []
    code = "import sys\nfor i in range(3): print(i)\nsys.stderr.write('half\\n')"
    result = python(code).do_with_each_line(seen.append).do_with_each_line(progress.append, from_errors=True).run()
    assert seen == ["0", "1", "2"] and progress == ["half"] and result.output.split() == ["0", "1", "2"]
    quiet = python("print('big')").do_with_each_line(seen.append, keep_output=False).run()
    assert quiet.output == "" and seen[-1] == "big"


def test_error_in_line_function_is_explained():
    def broken(line):
        raise ValueError("bad line")

    with pytest.raises(scmd.SimplyCommandError, match="bad line"):
        python("print(1)").do_with_each_line(broken).run()


def test_try_again_if_it_fails(tmp_path):
    counter = tmp_path / "n.txt"
    code = (f"import pathlib, sys; p = pathlib.Path(r'{counter}'); n = int(p.read_text()) + 1 if p.exists() else 1; "
            "p.write_text(str(n)); sys.exit(0 if n >= 3 else 1)")
    result = python(code).try_again_if_it_fails(times=3, wait=0).run()
    assert result.worked and result.attempts == 3 and "3 tries" in repr(result)
    counter.unlink()
    with pytest.raises(scmd.CommandFailedError):
        python(code).try_again_if_it_fails(times=2, wait=0).run()


def test_talk_to_a_running_program():
    code = "import sys\nfor line in sys.stdin: print(line.strip().upper(), flush=True)"
    running = python(code).keep_input_open().start_in_background()
    running.send_text("hello\n")
    assert running.wait_for_text("HELLO", time_limit=10)
    running.send_text("again\n").close_input()
    result = running.wait_until_done()
    assert result.output.split() == ["HELLO", "AGAIN"]
    assert isinstance(running.get_process_id(), int)


def test_send_text_needs_open_input():
    running = python("pass").start_in_background()
    with pytest.raises(scmd.SimplyCommandError, match="keep_input_open"):
        running.send_text("x")
    running.wait_until_done()


def test_stop_gently_stops_the_whole_tree():
    code = (f"import subprocess, time; subprocess.Popen([r'{PY}', '-c', 'import time; time.sleep(30)']); "
            "print('ready', flush=True); time.sleep(30)")
    running = python(code).start_in_background()
    assert running.wait_for_text("ready", time_limit=20)
    start = time.perf_counter()
    result = running.stop(gently=True, wait=1)
    assert result.stopped == "by you" and time.perf_counter() - start < 15


def test_priority_and_hidden_window():
    assert python("print(1)").set_priority("low").hide_window().run().output.strip() == "1"
    with pytest.raises(scmd.SimplyCommandError, match="low"):
        python("pass").set_priority("lowest")


def test_run_in_this_terminal_keeps_no_output():
    result = python("print('to the terminal')").run_in_this_terminal().run()
    assert result.worked and result.output == ""


def test_run_async_and_together_async():
    import asyncio

    async def main():
        one = await python("print(1)").run_async()
        many = await scmd.run_together_async([python(f"print({i})") for i in range(3)], at_most=2)
        return one, many

    one, many = asyncio.run(main())
    assert one.output.strip() == "1" and [r.output.strip() for r in many] == ["0", "1", "2"]


def test_named_shell():
    if ON_WINDOWS:
        assert scmd.run_in_shell("Write-Output 5", shell="powershell").output.strip() == "5"
    else:
        assert scmd.run_in_shell("echo $((2+3))", shell="sh").output.strip() == "5"
    with pytest.raises(scmd.SimplyCommandError, match="bash"):
        scmd.run_in_shell("x", shell="bsh")
    assert "hi" in scmd.make_shell_line("echo hi").set_time_limit(30).run().output


# ================================================================ other places to run
def test_python_environment(tmp_path):
    (tmp_path / ("Scripts" if ON_WINDOWS else "bin")).mkdir()
    env = python("import os; print(os.environ['VIRTUAL_ENV'])").use_python_environment(tmp_path)
    assert env.run().output.strip() == str(tmp_path)
    with pytest.raises(scmd.SimplyCommandError, match="Python environment"):
        python("pass").use_python_environment(tmp_path / "nothing")


def test_conda_words():
    assert scmd.program("fastqc", "a.fq").use_conda_environment("qc").get_command_words() == \
        ["conda", "run", "--no-capture-output", "-n", "qc", "fastqc", "a.fq"]
    assert scmd.program("x").use_conda_environment("envs/qc", using="micromamba").get_command_words() == \
        ["micromamba", "run", "-p", "envs/qc", "x"]


def test_container_words(tmp_path):
    words = (scmd.program("samtools", "view", "a.bam").set_folder(tmp_path).set_environment(A=1)
             .use_container("biocontainers/samtools:1.19").get_command_words())
    assert words[:4] == ["docker", "run", "--rm", "-i"]
    assert f"{tmp_path}:/work" in words and "A=1" in words and words[-3:] == ["samtools", "view", "a.bam"]
    words = scmd.program("x").use_container("img.sif", using="apptainer").get_command_words()
    assert words[:2] == ["apptainer", "exec"] and words[-2:] == ["img.sif", "x"]


def test_remote_words():
    prog = (scmd.program("samtools", "sort", "my file.bam").set_folder("/data/run 1").set_environment(T=2)
            .set_computer("me@server", port=2222, key_file="key"))
    words = prog.get_command_words()
    assert words[:6] == ["ssh", "-p", "2222", "-i", "key", "me@server"]
    assert words[6] == "cd '/data/run 1' && env T=2 samtools sort 'my file.bam'"
    assert prog.set_computer(None).get_command_words() == ["samtools", "sort", "my file.bam"]


def test_remote_container_conda_join():
    words = (scmd.program("fastqc", "a.fq").use_conda_environment("qc").use_container("img")
             .set_computer("me@server").get_command_words())
    assert words[:2] == ["ssh", "me@server"]
    assert "docker run" in words[2] and "conda run" in words[2]


# ================================================================ files and folders
def test_files_and_folders(tmp_path, capsys):
    data = tmp_path / "data"
    scmd.make_folder(data / "sub")
    (data / "a.fa").write_bytes(b">a\nACGT\n")
    (data / "sub" / "b.fa").write_bytes(b">b\nAC\n")
    (data / "notes.txt").write_bytes(b"x")
    assert [os.path.basename(f) for f in scmd.find_files("*.fa", in_folder=data)] == ["a.fa", "b.fa"]
    assert len(scmd.find_files("*.fa", in_folder=data, in_subfolders=False)) == 1
    copied = scmd.copy_file(data / "a.fa", to=str(tmp_path / "backup") + "/")
    assert os.path.isfile(copied) and copied.endswith("a.fa")
    scmd.move_file(copied, to=tmp_path / "backup" / "renamed.fa")
    assert (tmp_path / "backup" / "renamed.fa").exists()
    scmd.copy_folder(data, to=tmp_path / "data2")
    scmd.move_folder(tmp_path / "data2", to=tmp_path / "data3")
    assert scmd.find_size_of(data) == 8 + 6 + 1 and "bytes" in capsys.readouterr().out
    scmd.remove_file(data / "notes.txt")
    scmd.remove_file(data / "notes.txt", if_it_exists=True)
    scmd.remove_folder(tmp_path / "data3")
    assert not (tmp_path / "data3").exists()


def test_file_errors_guess(tmp_path):
    (tmp_path / "genes.fa").write_text("x")
    with pytest.raises(scmd.SimplyCommandError, match="genes.fa"):
        scmd.copy_file(tmp_path / "gens.fa", to=tmp_path / "x.fa")
    with pytest.raises(scmd.SimplyCommandError, match="copy_folder"):
        scmd.copy_file(tmp_path, to=tmp_path / "y")
    with pytest.raises(scmd.SimplyCommandError, match="home folder"):
        scmd.remove_folder(os.path.expanduser("~"))


@pytest.mark.parametrize("ending", [".zip", ".tar.gz", ".tar.xz"])
def test_pack_and_unpack(tmp_path, ending):
    (tmp_path / "res" / "plots").mkdir(parents=True)
    (tmp_path / "res" / "plots" / "p.txt").write_text("plot")
    (tmp_path / "table.csv").write_text("a,b")
    archive = scmd.pack_into(tmp_path / f"out{ending}", tmp_path / "res", tmp_path / "table.csv")
    scmd.unpack(archive, into=tmp_path / "back")
    assert (tmp_path / "back" / "res" / "plots" / "p.txt").read_text() == "plot"
    assert (tmp_path / "back" / "table.csv").read_text() == "a,b"


def test_unpack_refuses_files_outside(tmp_path):
    import zipfile

    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../escape.txt", "x")
    with pytest.raises(scmd.SimplyCommandError, match="outside"):
        scmd.unpack(bad, into=tmp_path / "in")


def test_current_folder(tmp_path):
    here = scmd.get_current_folder()
    try:
        assert os.path.samefile(scmd.set_current_folder(tmp_path), tmp_path)
    finally:
        os.chdir(here)


def test_download_file_from_a_local_server(tmp_path):
    import functools
    import http.server
    import threading

    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "genome.fa").write_bytes(b">g\nACGT\n")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path / "site"))
    handler.log_message = lambda *a: None
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        path = scmd.download_file(f"http://127.0.0.1:{server.server_port}/genome.fa", to=str(tmp_path / "ref") + "/")
        assert open(path, "rb").read() == b">g\nACGT\n"
        with pytest.raises(scmd.SimplyCommandError, match="did not work"):
            scmd.download_file(f"http://127.0.0.1:{server.server_port}/missing.fa", to=str(tmp_path / "ref") + "/")
    finally:
        server.shutdown()


def test_other_names_point_to_words():
    with pytest.raises(AttributeError, match="scmd.find_files"):
        scmd.glob
    with pytest.raises(AttributeError, match="start_in_background"):
        scmd.Popen


# ================================================================ command-line programs, more
class Tools(scmd.CommandLineProgram):
    """Tools with shared options."""
    version = "2.5"

    def __init__(self, verbose: bool = False, prefix: str = ">"):
        """verbose (-v): say more
        prefix: put this before answers
        """
        self.verbose, self.prefix = verbose, prefix

    def convert(self, name: str, to: Literal["fastq", "tsv"] = "tsv", min_length: int = 0):
        """Convert a file.
        min_length (-m): shortest to keep
        """
        return f"{self.prefix}{name}->{to} m={min_length} v={self.verbose}"

    def listing(self):
        """Give a list."""
        return ["a", "b"]


def test_init_options_short_letters_and_choices(capsys):
    assert Tools.start_from_command_line(["-v", "--prefix", "#", "convert", "x", "--to", "fastq", "-m", "5"]) == \
        "#x->fastq m=5 v=True"
    assert Tools().start_from_command_line(["convert", "x"]) == ">x->tsv m=0 v=False"
    capsys.readouterr()
    with pytest.raises(SystemExit):
        Tools.start_from_command_line(["convert", "x", "--to", "fasta"])
    assert "invalid choice" in capsys.readouterr().err


def test_version_and_list_printing(capsys):
    with pytest.raises(SystemExit):
        Tools.start_from_command_line(["--version"])
    assert "2.5" in capsys.readouterr().out
    Tools.start_from_command_line(["listing"])
    assert capsys.readouterr().out.split() == ["a", "b"]
    assert Tools.get_commands() == ["convert", "listing"]


def test_make_command_line_program_from_class_with_init():
    assert scmd.make_command_line_program(Tools, ["--prefix", "!", "convert", "y"]) == "!y->tsv m=0 v=False"
