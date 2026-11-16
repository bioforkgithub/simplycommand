"""Talking to the person at the terminal: questions, yes or no, passwords, choices, colours and
progress bars (what click and typer add on top of argparse), with nothing but the standard library.

    name = scmd.ask("Sample name", default="S1")
    if scmd.ask_yes_or_no("Delete the old results?", default=False): ...
    for file in scmd.show_progress(files, label="Checking"): ...
    scmd.write_in_colour("Done", "green")
"""

from __future__ import annotations

import getpass
import os
import sys
import time

from ._errors import SimplyCommandError, choice_error

COLOURS = {"black": 30, "red": 31, "green": 32, "yellow": 33, "blue": 34, "magenta": 35, "cyan": 36,
           "white": 37, "grey": 90}
_COLOURS_READY = False


def _input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        raise SimplyCommandError("There is no one to answer: the program's input is closed "
                                 "(give the answer as an option instead).") from None


def ask(question: str, default=None, kind=str):
    """Ask a question in the terminal and give the answer. kind=int or float turns it into a number
    (and asks again if it is not one). Enter alone gives the default."""
    shown = f" [{default}]" if default is not None else ""
    while True:
        answer = _input(f"{question}{shown}: ").strip()
        if not answer:
            if default is not None:
                return default
            continue
        try:
            return kind(answer)
        except ValueError:
            print(f"Please give a {'whole number' if kind is int else 'number' if kind is float else 'value'}.")


def ask_yes_or_no(question: str, default: bool | None = None) -> bool:
    """Ask a yes-or-no question in the terminal and give True or False."""
    shown = {True: " [Y/n]", False: " [y/N]", None: " [y/n]"}[default]
    while True:
        answer = _input(f"{question}{shown}: ").strip().lower()
        if not answer and default is not None:
            return default
        if answer in ("y", "yes", "j", "ja"):
            return True
        if answer in ("n", "no", "nei", "nein"):
            return False
        print('Please answer "y" or "n".')


def ask_for_password(question: str = "Password") -> str:
    """Ask for a password in the terminal without showing what is typed."""
    return getpass.getpass(f"{question}: ")


def ask_to_choose(question: str, choices, default=None):
    """Ask the person to choose one of a list, by number or by name, and give the choice."""
    choices = list(choices)
    if not choices:
        raise SimplyCommandError("ask_to_choose needs at least one choice.")
    if default is not None and default not in choices:
        raise choice_error("ask_to_choose", "default", default, choices)
    print(question)
    for number, choice in enumerate(choices, 1):
        print(f"  {number}. {choice}")
    while True:
        answer = _input(f"Choose 1-{len(choices)}" + (f" [{default}]" if default is not None else "") + ": ").strip()
        if not answer and default is not None:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        matches = [c for c in choices if str(c).lower() == answer.lower()]
        if matches:
            return matches[0]
        print(f"Please give a number from 1 to {len(choices)}.")


def _colours_work(stream) -> bool:
    global _COLOURS_READY
    if os.environ.get("NO_COLOR") or not hasattr(stream, "isatty") or not stream.isatty():
        return bool(os.environ.get("FORCE_COLOR"))
    if os.name == "nt" and not _COLOURS_READY:
        try:  # switch on colour codes in the Windows console
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:  # noqa: BLE001  (no colours, then)
            pass
    _COLOURS_READY = True
    return True


def colour_text(text: str, colour: str, bold: bool = False) -> str:
    """The text with colour codes around it (for print). Colours: black, red, green, yellow, blue, magenta,
    cyan, white, grey. No codes are added when the output is not a terminal or NO_COLOR is set."""
    name = {"gray": "grey", "color": "colour"}.get(colour, colour)
    if name not in COLOURS:
        raise choice_error("write_in_colour", "colour", colour, list(COLOURS))
    if not _colours_work(sys.stdout):
        return str(text)
    return f"\033[{'1;' if bold else ''}{COLOURS[name]}m{text}\033[0m"


def write_in_colour(text: str, colour: str, bold: bool = False) -> None:
    """Print text in a colour: write_in_colour("Done", "green"), write_in_colour("Failed", "red", bold=True)."""
    print(colour_text(text, colour, bold))


def show_progress(items, label: str = "", total: int | None = None, width: int = 30):
    """Go through items while showing a progress bar with the time left:
    for file in scmd.show_progress(files, label="Checking"): ...

    The bar is written to the error stream, so the output stays clean.
    """
    if total is None:
        try:
            total = len(items)
        except TypeError:
            total = None
    stream = sys.stderr
    drawing = hasattr(stream, "isatty") and stream.isatty()
    start = time.perf_counter()
    last_drawn = 0.0
    done = 0

    def draw(final=False):
        nonlocal last_drawn
        now = time.perf_counter()
        if not final and now - last_drawn < 0.1:
            return
        last_drawn = now
        took = now - start
        if total:
            share = min(done / total, 1.0)
            bar = "#" * int(width * share) + "-" * (width - int(width * share))
            left = (took / done * (total - done)) if done else 0
            text = f"\r{label} [{bar}] {done}/{total} {share:4.0%}  {_clock(left)} left "
        else:
            text = f"\r{label} {done} done  {_clock(took)} "
        if drawing:
            stream.write(text)
            stream.flush()
        elif final:
            stream.write(text.strip("\r") + "\n")

    for item in items:
        yield item
        done += 1
        draw()
    draw(final=True)
    if drawing:
        stream.write("\n")
        stream.flush()


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else \
        f"{seconds // 60}:{seconds % 60:02d}"
