"""What a command gave back: its output, its errors, whether it worked and how long it took."""

from __future__ import annotations

import json
import os

from ._errors import SimplyCommandError, missing_word_error, own_words


class Result:
    """What a finished command gave back.

        result = scmd.program("git").run("status")
        result.worked          # True or False
        result.output          # the text it wrote
        result.errors          # the text it wrote on its error stream
        result.show_output()
    """

    def __init__(self, command_line: str, exit_codes: list[int], output: str, errors: str,
                 seconds: float, folder: str, output_file: str | None = None, stopped: str | None = None,
                 accepted_codes=frozenset({0}), output_bytes: bytes | None = None,
                 cpu_seconds: float | None = None, peak_memory_mb: float | None = None):
        self.command_line = command_line
        self.exit_codes = list(exit_codes)
        self.output = output
        self.errors = errors
        self.seconds = seconds
        self.folder = folder
        self.output_file = output_file
        self.stopped = stopped  # None, "time limit" or "by you"
        self.accepted_codes = frozenset(accepted_codes)
        self.attempts = 1
        self.cpu_seconds = cpu_seconds          # CPU time used by the program and all it started (None: unknown)
        self.peak_memory_mb = peak_memory_mb    # the most memory it used at once, in MB (None: unknown)
        self._output_bytes = output_bytes if output_bytes is not None else output.encode("utf-8")

    # ------------------------------------------------------------ plain facts
    @property
    def exit_code(self) -> int:
        """The exit code of the command (the last one, for a pipe). 0 means it worked."""
        return self.exit_codes[-1] if self.exit_codes else -1

    @property
    def worked(self) -> bool:
        """True when every program in the command ended well (exit code 0, or a code you accepted)."""
        return (self.stopped is None and bool(self.exit_codes)
                and all(code in self.accepted_codes for code in self.exit_codes))

    def describe_exit(self) -> str:
        """How the command ended, in words: "exit code 2", or "stopped by signal SIGKILL" on Linux and macOS."""
        parts = []
        for code in self.exit_codes:
            if code < 0:
                try:
                    import signal

                    parts.append(f"stopped by signal {signal.Signals(-code).name}")
                except ValueError:
                    parts.append(f"stopped by signal {-code}")
            else:
                parts.append(f"exit code {code}")
        return ", ".join(parts) if len(set(parts)) > 1 else (parts[0] if parts else "not started")

    def __bool__(self) -> bool:
        return self.worked

    def __str__(self) -> str:
        return self.output

    def __repr__(self) -> str:
        return self.describe(quiet=True)

    def describe(self, quiet: bool = False) -> str:
        """Say in one sentence what happened: worked or failed, how long it took, how much it wrote."""
        time = f"{self.seconds:.2f} seconds" if self.seconds < 60 else f"{self.seconds / 60:.1f} minutes"
        if self.stopped == "time limit":
            text = f'The command "{self.command_line}" was stopped at its time limit, after {time}.'
        elif self.stopped:
            text = f'The command "{self.command_line}" was stopped {self.stopped}, after {time}.'
        elif self.worked:
            where = f'into "{self.output_file}"' if self.output_file else f"{_count(self.output, 'line')} of output"
            text = f'The command "{self.command_line}" worked in {time} and wrote {where}.'
        else:
            text = f'The command "{self.command_line}" failed ({self.describe_exit()}) after {time}.'
            last = _last_lines(self.errors, 1)
            if last:
                text += f' Its last error line: "{last}"'
        if self.attempts > 1:
            text += f" It took {self.attempts} tries."
        if not quiet:
            print(text)
        return text

    # ------------------------------------------------------------ look at it
    def show_output(self) -> "Result":
        """Print the text the command wrote."""
        print(self.output, end="" if self.output.endswith("\n") else "\n")
        return self

    def show_errors(self) -> "Result":
        """Print the text the command wrote on its error stream (many tools write progress there too)."""
        print(self.errors, end="" if self.errors.endswith("\n") else "\n")
        return self

    # ------------------------------------------------------------ take parts out
    def get_output_lines(self, keep_empty: bool = False) -> list[str]:
        """The output as a list of lines (empty lines left out unless keep_empty=True)."""
        lines = self.output.splitlines()
        return lines if keep_empty else [line for line in lines if line.strip()]

    def get_error_lines(self, keep_empty: bool = False) -> list[str]:
        """The error stream as a list of lines (empty lines left out unless keep_empty=True)."""
        lines = self.errors.splitlines()
        return lines if keep_empty else [line for line in lines if line.strip()]

    def get_output_as_rows(self, separator: str | None = None, skip_lines_starting_with: str | None = "#") -> list[list[str]]:
        """The output as rows of cells. Cells are split on tabs if there are any, otherwise on spaces.

        separator="," splits on commas. Lines starting with "#" (comments) are left out;
        skip_lines_starting_with=None keeps them.
        """
        lines = self.get_output_lines()
        if skip_lines_starting_with:
            lines = [line for line in lines if not line.startswith(skip_lines_starting_with)]
        if separator is None:
            separator = "\t" if any("\t" in line for line in lines) else None
        return [line.split(separator) if separator else line.split() for line in lines]

    def get_output_as_bytes(self) -> bytes:
        """The output exactly as the program wrote it, as bytes (for images, archives and other binary output)."""
        return self._output_bytes

    def get_output_as_json(self):
        """The output read as JSON (for tools that answer in JSON, such as `gh` or `docker inspect`)."""
        try:
            return json.loads(self.output)
        except json.JSONDecodeError as error:
            start = self.output[:80].replace("\n", " ")
            raise SimplyCommandError(f"The output is not JSON ({error.msg} at line {error.lineno}).\n"
                                     f'It starts with: "{start}"') from None

    def find_lines_with(self, text: str, ignore_case: bool = False) -> list[str]:
        """The lines of the output that contain `text` (like grep)."""
        if ignore_case:
            low = text.lower()
            return [line for line in self.get_output_lines() if low in line.lower()]
        return [line for line in self.get_output_lines() if text in line]

    # ------------------------------------------------------------ save
    def save_output(self, file_name) -> "Result":
        """Write the output to a text file."""
        _write(file_name, self.output)
        return self

    def save_errors(self, file_name) -> "Result":
        """Write the error stream to a text file."""
        _write(file_name, self.errors)
        return self

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise missing_word_error("result", name, own_words(self))


def _write(file_name, text: str) -> None:
    folder = os.path.dirname(os.fspath(file_name))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(file_name, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _count(text: str, word: str) -> str:
    n = len(text.splitlines())
    return f"{n} {word}" + ("" if n == 1 else "s")


def _last_lines(text: str, n: int) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-n:])
