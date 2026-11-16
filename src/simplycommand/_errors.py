"""Friendly error messages.

simplycommand never shows a confusing Python or operating-system error if it can help it.
Every message says what went wrong, guesses what was meant, and says what to do next.
"""

from __future__ import annotations

import difflib
import os
import sys

ISSUES_URL = "https://github.com/bioforkgithub/simplycommand/issues"
ON_WINDOWS = sys.platform.startswith("win")

# Commands that live inside the shell itself (cmd.exe or sh), so there is no program file to run.
SHELL_WORDS_WINDOWS = {"dir", "echo", "type", "copy", "del", "erase", "move", "ren", "rename", "md", "mkdir",
                       "rd", "rmdir", "cd", "chdir", "set", "cls", "ver", "vol", "start", "mklink", "pushd", "popd"}
SHELL_WORDS_POSIX = {"cd", "alias", "export", "source", "set", "unset", "ulimit", "umask", "history", "type"}

# Linux tools that are often missing on Windows, and what Windows has instead.
WINDOWS_INSTEAD = {"ls": "dir", "cat": "type", "grep": "findstr", "rm": "del", "cp": "copy", "mv": "move",
                   "touch": "type nul >", "which": "where", "clear": "cls", "head": "more", "pwd": "cd"}


class SimplyCommandError(Exception):
    """A problem explained in plain English."""


class MissingWordError(SimplyCommandError, AttributeError):
    """Asked for a word simplycommand does not have. Also an AttributeError, so hasattr() keeps working."""


class ProgramNotFoundError(SimplyCommandError, FileNotFoundError):
    """The program to run is not installed, or its folder is not on the PATH."""


class CommandFailedError(SimplyCommandError):
    """The command ran but said it failed (its exit code was not 0). The result is in .result."""

    def __init__(self, message: str, result):
        super().__init__(message)
        self.result = result


class TimeLimitError(SimplyCommandError, TimeoutError):
    """The command ran longer than its time limit and was stopped. What it wrote so far is in .result."""

    def __init__(self, message: str, result):
        super().__init__(message)
        self.result = result


def suggest(word: str, options, n: int = 3, cutoff: float = 0.6) -> list[str]:
    """The closest matches to `word` among `options`."""
    return difflib.get_close_matches(str(word), [str(o) for o in options], n=n, cutoff=cutoff)


def own_words(obj) -> list[str]:
    """The public words (methods and properties) of an object's class."""
    return sorted(name for name in dir(type(obj)) if not name.startswith("_"))


def missing_word_error(kind: str, word: str, known) -> MissingWordError:
    lines = [f"A {kind} has no word called .{word}."]
    guesses = suggest(word, known)
    if guesses:
        lines.append("Did you mean " + " or ".join(f".{g}" for g in guesses) + "?")
    lines.append("Type scmd.show_all_words() to see every word.")
    lines.append(f"Missing something? Ask for it at {ISSUES_URL}")
    return MissingWordError("\n".join(lines))


def choice_error(word: str, option: str, value, choices) -> SimplyCommandError:
    lines = [f'{word} does not know {option}="{value}".']
    guesses = suggest(value, choices, n=1)
    if guesses:
        lines.append(f'Did you mean {option}="{guesses[0]}"?')
    lines.append("You can use: " + ", ".join(f'"{c}"' for c in choices))
    return SimplyCommandError("\n".join(lines))


def _programs_on_path(path: str | None) -> set[str]:
    """Every program name found in the folders of the PATH (without .exe/.bat/.cmd on Windows)."""
    found: set[str] = set()
    endings = {e.lower() for e in os.environ.get("PATHEXT", ".EXE;.BAT;.CMD;.COM").split(";")} if ON_WINDOWS else set()
    for folder in (path or os.environ.get("PATH", "")).split(os.pathsep):
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            stem, ending = os.path.splitext(name)
            if ON_WINDOWS:
                if ending.lower() in endings:
                    found.add(stem)
            else:
                found.add(name)
    return found


def program_not_found_error(name: str, path: str | None = None) -> ProgramNotFoundError:
    lines = [f'The program "{name}" was not found on this computer.']
    shell_words = SHELL_WORDS_WINDOWS if ON_WINDOWS else SHELL_WORDS_POSIX
    if name.lower() in shell_words:
        lines.append(f'"{name}" is part of the shell, not a program of its own. '
                     f'Run it with scmd.run_in_shell("{name} ...").')
    elif ON_WINDOWS and name in WINDOWS_INSTEAD:
        lines.append(f'"{name}" is a Linux command. On Windows the command is "{WINDOWS_INSTEAD[name]}" '
                     f'(run it with scmd.run_in_shell), or install Git for Windows or WSL to get "{name}".')
    else:
        guesses = suggest(name, _programs_on_path(path), n=3, cutoff=0.65)
        if guesses:
            lines.append("Did you mean " + " or ".join(f'"{g}"' for g in guesses) + "?")
        lines.append("Check that it is installed and that its folder is on your PATH.")
        lines.append("You can also give the full path, for example "
                     + (r'scmd.program(r"C:\tools\samtools.exe").' if ON_WINDOWS else 'scmd.program("/opt/tools/samtools").'))
    return ProgramNotFoundError("\n".join(lines))
