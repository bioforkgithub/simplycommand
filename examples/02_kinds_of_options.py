"""Step 2: every kind of option, in one program that counts the words in text files.

Try in the terminal:
    python 02_kinds_of_options.py 01_hello.py
    python 02_kinds_of_options.py 01_hello.py 02_kinds_of_options.py --top 5
    python 02_kinds_of_options.py *.py --min-length 6 --sort word --ignore-case
    python 02_kinds_of_options.py 01_hello.py --save counts.txt --no-numbers
    python 02_kinds_of_options.py --help

How each kind is written:
    files: list[Path]                   many words given in order (one or more files)
    min_length: int = 1                 an option that takes a whole number
    top: int | None = None              an option you may leave out (None: not given)
    sort: Literal["count", "word"]      only these choices are allowed (--sort word)
    ignore_case: bool = False           a switch, off unless given (--ignore-case)
    numbers: bool = True                on unless switched off (--no-numbers)
    save: Path | None = None            a file name
"""

from collections import Counter
from pathlib import Path
from typing import Literal

import simplycommand as scmd


def count_words(files: list[Path], min_length: int = 1, top: int | None = None,
                sort: Literal["count", "word"] = "count", ignore_case: bool = False,
                numbers: bool = True, save: Path | None = None):
    """Count how often each word appears in text files.
    files: the text files to read
    min_length (-m): leave out words shorter than this
    top (-n): show only this many words
    sort: order by "count" (most first) or by "word" (A to Z)
    ignore_case (-i): count "The" and "the" as one word
    numbers: show how often each word appears
    save: also write the answer into this file
    """
    counts = Counter()
    for file in files:
        if not file.is_file():
            # a SimplyCommandError is shown as a plain message, without a Python traceback
            raise scmd.SimplyCommandError(f'"{file}" is not a file.')
        text = file.read_text(encoding="utf-8", errors="replace")
        if ignore_case:
            text = text.lower()
        words = "".join(c if c.isalnum() else " " for c in text).split()
        counts.update(w for w in words if len(w) >= min_length)

    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]) if sort == "count" else kv[0])
    if top is not None:
        rows = rows[:top]
    lines = [f"{count:6}  {word}" if numbers else word for word, count in rows]
    if save is not None:
        save.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


if __name__ == "__main__":
    scmd.make_command_line_program(count_words)
