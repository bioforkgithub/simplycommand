"""Turning Python options into command-line words.

Every tool writes its options in its own way. You show simplycommand one example, the way the
tool's own help writes it, and it writes all options like that:

    "--long-name"        threads=4 -> --threads 4, o="x" -> -o x   (most Linux tools; the default)
    "-long_name"         max_target_seqs=5 -> -max_target_seqs 5    (BLAST)
    "-long-name"         -> -max-target-seqs 5
    "--long_name"        -> --max_target_seqs 5
    "--long-name=value"  -> --threads=4
    "/name"              -> /threads 4                              (old Windows tools)
"""

from __future__ import annotations

import os

from ._errors import SimplyCommandError, choice_error

STYLES = ["--long-name", "-long_name", "-long-name", "--long_name", "--long-name=value", "--long_name=value",
          "-long_name=value", "-long-name=value", "/name", "/name:value"]


class OptionStyle:
    """How a tool writes its option names, read from one example such as "--long-name"."""

    def __init__(self, example: str = "--long-name"):
        text = str(example).strip()
        prefix = text[: len(text) - len(text.lstrip("-/"))]
        if prefix not in ("-", "--", "/") or not text[len(prefix):]:
            raise choice_error("option_style=", "option_style", example, STYLES)
        self.example = text
        self.prefix = prefix
        body = text[len(prefix):]
        self.between = "=" if "=" in body else (":" if ":" in body else None)
        if self.between:
            body = body.split(self.between)[0]
        self.joiner = "_" if "_" in body else "-"

    def __repr__(self):
        return f"OptionStyle({self.example!r})"

    def flag(self, name) -> str:
        """The option name as the tool wants it: "threads" -> "--threads", "o" -> "-o"."""
        name = str(name)
        if name.startswith(("-", "/")):  # already written in full: leave it alone
            return name
        if not name:
            raise SimplyCommandError("An option needs a name, for example add_option(\"threads\", 4).")
        if name.endswith("_") and len(name) > 1:  # in_="x" -> --in, because "in" is a Python word
            name = name.rstrip("_")
        if self.joiner == "-":
            name = name.replace("_", "-")
        if len(name) == 1 and self.prefix == "--":
            return "-" + name
        return self.prefix + name

    def words(self, name, *values) -> list[str]:
        """The words for one option: ("threads", 4) -> ["--threads", "4"].

        True gives the name alone (a switch), False or None gives nothing, a list repeats the
        option for each value, and several values follow one name: ("files", "a", "b") -> --files a b.
        """
        if len(values) == 1:
            value = values[0]
            if value is True:
                return [self.flag(name)]
            if value is False or value is None:
                return []
            if isinstance(value, (list, tuple, set)):
                words: list[str] = []
                for each in value:
                    words += self.words(name, each)
                return words
        flag = self.flag(name)
        texts = [as_word(v) for v in values]
        short = len(flag) == 2 and flag.startswith("-") and self.prefix == "--"
        if self.between and len(texts) == 1 and not short:
            return [f"{flag}{self.between}{texts[0]}"]
        return [flag, *texts]


def as_word(value) -> str:
    """One command-line word from a Python value (numbers, text, paths)."""
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
