"""simplycommand: make command-line programs in Python with simple words, and run other programs.

    import simplycommand as scmd

    samtools = scmd.program("samtools")
    result = samtools.run("sort", "reads.bam", o="sorted.bam", threads=4)
    result.worked                                  # True or False

    git = scmd.program("git")
    git.status().show_output()                     # git status
    git.commit(m="Fix the plot")                   # git commit -m "Fix the plot"

    lines = scmd.program("zcat", "reads.fq.gz") | scmd.program("wc", "-l")
    lines.run().output

    scmd.find_files("*.fastq.gz", in_folder="raw") # files and folders in plain words too

Every word: scmd.show_all_words(). One word: scmd.help("add_option"). Lessons: scmd.show_lesson(1).
"""

from __future__ import annotations

import asyncio
import os
import shlex
from concurrent.futures import ThreadPoolExecutor

from . import _errors
from ._errors import (ON_WINDOWS, CommandFailedError, MissingWordError, ProgramNotFoundError, SimplyCommandError,
                      TimeLimitError)
from ._running import SETTINGS, RunningCommand
from .command_line_program import CommandLineProgram, make_command_line_program
from .files import (copy_file, copy_folder, download_file, find_files, find_free_space, find_size_of,
                    find_where_link_points, get_current_folder, get_file_dates, get_files_from, make_folder, make_link,
                    make_runnable, make_temporary_file, make_temporary_folder, move_file, move_folder, pack_into,
                    remove_file, remove_folder, send_files_to, set_current_folder, set_owner, set_permissions, unpack,
                    wait_for_change_in)
from .talk import (ask, ask_for_password, ask_to_choose, ask_yes_or_no, colour_text, show_progress,
                   write_in_colour)
from .program import Pipeline, Program, ShellLine
from .result import Result

__version__ = "0.3.0"


def program(name, *words, option_style: str | None = None, **options) -> Program:
    """Start a program to build up and run: scmd.program("samtools").

    Words and options given here stay with the program for every run:
    scmd.program("blastn", option_style="-long_name", db="nt").
    """
    return Program(name, *words, option_style=option_style, **options)


def run_line(line: str, *, folder=None, keep_going_if_it_fails: bool = False) -> Result:
    """Run a whole command written as one line, the way you would type it: scmd.run_line("git log -n 3").

    The line is split into words (quotes keep words together); no shell is used, so | and > do not work
    here (use scmd.run_in_shell for those).
    """
    words = _split(line)
    if not words:
        raise SimplyCommandError("The line is empty: give a command, for example scmd.run_line(\"git status\").")
    prog = Program(words[0], *words[1:]).set_folder(folder)
    if keep_going_if_it_fails:
        prog.keep_going_if_it_fails()
    return prog.run()


def run_in_shell(line: str, *, shell: str | None = None, folder=None, keep_going_if_it_fails: bool = False) -> Result:
    """Run a line in a shell, with its | > && and its own words such as dir and echo:
    scmd.run_in_shell("dir /b *.fasta").

    Without shell= it is this computer's own shell (cmd.exe on Windows, sh elsewhere); shell= "bash",
    "zsh", "sh", "powershell", "pwsh" or "cmd" picks one. Prefer scmd.program for file names from
    outside: a shell reads special characters in them.
    """
    prog = ShellLine(line, shell=shell).set_folder(folder)
    if keep_going_if_it_fails:
        prog.keep_going_if_it_fails()
    return prog.run()


def make_shell_line(line: str, shell: str | None = None) -> ShellLine:
    """A shell line as a program, to set up before running (folder, time limit, input ...):
    scmd.make_shell_line("sort data.txt | uniq -c").set_time_limit(60).run()."""
    return ShellLine(line, shell=shell)


def find_program(name: str) -> str | None:
    """Say where a program is on this computer, and give its full path (None if it is not found)."""
    return Program(name).find_where_installed()


def run_together(programs, at_most: int | None = None) -> list[Result]:
    """Run many programs at the same time and wait for all of them. Gives their results in the same order.

        jobs = [scmd.program("fastqc", f) for f in ["a.fq", "b.fq", "c.fq"]]
        results = scmd.run_together(jobs, at_most=2)     # two at a time
    """
    programs = _check_programs(programs)
    if not programs:
        return []
    with ThreadPoolExecutor(max_workers=at_most or min(len(programs), os.cpu_count() or 4)) as pool:
        return list(pool.map(lambda p: p.run(), programs))


async def run_together_async(programs, at_most: int | None = None) -> list[Result]:
    """The same as run_together, for async code: results = await scmd.run_together_async(jobs, at_most=4)."""
    programs = _check_programs(programs)
    gate = asyncio.Semaphore(at_most or len(programs) or 1)

    async def one(prog):
        async with gate:
            return await prog.run_async()

    return list(await asyncio.gather(*(one(p) for p in programs)))


def _check_programs(programs) -> list:
    programs = list(programs)
    for each in programs:
        if not isinstance(each, (Program, Pipeline)):
            raise SimplyCommandError(f"Give programs made with scmd.program(...), not a {type(each).__name__}.")
    return programs


def start_showing_commands() -> None:
    """From now on, print each command before it runs (good for checking what really happens)."""
    SETTINGS["show_commands"] = True


def stop_showing_commands() -> None:
    """Stop printing each command before it runs."""
    SETTINGS["show_commands"] = False


def start_log_in(file_name) -> None:
    """From now on, write every command, its folder, whether it worked and how long it took into this file.

    Useful for the Methods section of a paper: the log says exactly what was run.
    """
    file_name = os.path.abspath(os.fspath(file_name))
    os.makedirs(os.path.dirname(file_name), exist_ok=True)
    SETTINGS["log_file"] = file_name


def stop_log() -> None:
    """Stop writing commands into the log file."""
    SETTINGS["log_file"] = None


def _split(line: str) -> list[str]:
    if not ON_WINDOWS:
        return shlex.split(line)
    # On Windows a backslash is part of a path, not a quote sign.
    words = shlex.split(line, posix=False)
    return [w[1:-1] if len(w) >= 2 and w[0] == w[-1] and w[0] in "\"'" else w for w in words]


from .learn import help, show_all_words, show_lesson  # noqa: E402  (learn reads the words above)

# Names from subprocess, shutil, os and the shell: they never run, they point to the simplycommand word.
OTHER_NAMES = {
    "run": "scmd.program(...).run() or scmd.run_line(...)", "call": "scmd.program(...).run()",
    "check_call": "scmd.program(...).run()", "check_output": "scmd.program(...).run().output",
    "Popen": "scmd.program(...).start_in_background()", "system": "scmd.run_in_shell(...)",
    "shell": "scmd.run_in_shell(...)", "which": "scmd.find_program(...)", "where": "scmd.find_program(...)",
    "copy": "scmd.copy_file(...) or scmd.copy_folder(...)", "copy2": "scmd.copy_file(...)",
    "copytree": "scmd.copy_folder(...)", "cp": "scmd.copy_file(...)", "move": "scmd.move_file(...)",
    "mv": "scmd.move_file(...)", "rename": "scmd.move_file(...)", "rmtree": "scmd.remove_folder(...)",
    "remove": "scmd.remove_file(...)", "unlink": "scmd.remove_file(...)", "rm": "scmd.remove_file(...)",
    "makedirs": "scmd.make_folder(...)", "mkdir": "scmd.make_folder(...)", "glob": "scmd.find_files(...)",
    "find": "scmd.find_files(...)", "walk": "scmd.find_files(...)", "getcwd": "scmd.get_current_folder()",
    "pwd": "scmd.get_current_folder()", "chdir": "scmd.set_current_folder(...)", "cd": "scmd.set_current_folder(...)",
    "make_archive": "scmd.pack_into(...)", "zip": "scmd.pack_into(...)", "tar": "scmd.pack_into(...)",
    "unpack_archive": "scmd.unpack(...)", "unzip": "scmd.unpack(...)", "urlretrieve": "scmd.download_file(...)",
    "wget": "scmd.download_file(...)", "curl": "scmd.download_file(...)", "getsize": "scmd.find_size_of(...)",
    "du": "scmd.find_size_of(...)", "gather": "scmd.run_together(...)",
    "chmod": "scmd.set_permissions(...) or scmd.make_runnable(...)", "chown": "scmd.set_owner(...)",
    "symlink": "scmd.make_link(...)", "ln": "scmd.make_link(...)", "readlink": "scmd.find_where_link_points(...)",
    "disk_usage": "scmd.find_free_space(...)", "df": "scmd.find_free_space(...)",
    "mkdtemp": "scmd.make_temporary_folder()", "mkstemp": "scmd.make_temporary_file()",
    "TemporaryDirectory": "scmd.make_temporary_folder()", "stat": "scmd.get_file_dates(...)",
    "getmtime": "scmd.get_file_dates(...)", "scp": "scmd.send_files_to(...) or scmd.get_files_from(...)",
    "rsync": 'scmd.send_files_to(..., using="rsync")', "input": "scmd.ask(...)", "prompt": "scmd.ask(...)",
    "confirm": "scmd.ask_yes_or_no(...)", "getpass": "scmd.ask_for_password(...)", "tqdm": "scmd.show_progress(...)",
    "progressbar": "scmd.show_progress(...)", "echo": "scmd.write_in_colour(...) or print",
    "secho": "scmd.write_in_colour(...)", "style": "scmd.colour_text(...)", "pexpect": "program.run_in_pseudo_terminal()",
    "spawn": "program.run_in_pseudo_terminal().start_in_background()", "kill": "running.send_signal(...) or running.stop()",
    "nohup": "program.start_and_leave_running()", "daemon": "program.start_and_leave_running()",
    "sudo": "program.run_as_administrator()", "setrlimit": "program.set_memory_limit(...) / set_cpu_time_limit(...)",
    "ulimit": "program.set_memory_limit(...) / set_cpu_time_limit(...)", "watch": "scmd.wait_for_change_in(...)",
}


def __getattr__(name):
    if name.startswith("_"):
        raise AttributeError(f"module 'simplycommand' has no attribute {name!r}")
    lines = [f"simplycommand has no word called scmd.{name}."]
    if name in OTHER_NAMES:
        lines.append(f"In simplycommand this is {OTHER_NAMES[name]}.")
    else:
        guesses = _errors.suggest(name, [w for w in __all__ if not w[0].isupper()])
        if guesses:
            lines.append("Did you mean " + " or ".join(f"scmd.{g}()" for g in guesses) + "?")
    lines.append("Type scmd.show_all_words() to see every word.")
    raise MissingWordError("\n".join(lines))


__all__ = [
    "CommandFailedError", "CommandLineProgram", "MissingWordError", "Pipeline", "Program", "ProgramNotFoundError",
    "Result", "RunningCommand", "SimplyCommandError", "TimeLimitError",
    "ask", "ask_for_password", "ask_to_choose", "ask_yes_or_no", "colour_text", "copy_file", "copy_folder",
    "download_file", "find_files", "find_free_space", "find_program", "find_size_of", "find_where_link_points",
    "get_current_folder", "get_file_dates", "get_files_from", "help", "make_command_line_program", "make_folder",
    "make_link", "make_runnable", "make_shell_line", "make_temporary_file", "make_temporary_folder", "move_file",
    "move_folder", "pack_into", "program", "remove_file", "remove_folder", "run_in_shell", "run_line", "run_together",
    "run_together_async", "send_files_to", "set_current_folder", "set_owner", "set_permissions", "show_all_words",
    "show_lesson", "show_progress", "start_log_in", "start_showing_commands", "stop_log", "stop_showing_commands",
    "unpack", "wait_for_change_in", "write_in_colour",
]
