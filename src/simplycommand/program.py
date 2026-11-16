"""Program: one command-line program, built up step by step and run when you are ready.

    import simplycommand as scmd

    samtools = scmd.program("samtools")
    result = samtools.run("sort", "reads.bam", o="sorted.bam", threads=4)
    result.worked

    git = scmd.program("git")
    git.status()                       # runs: git status
    git.commit(m="Fix the plot")       # runs: git commit -m "Fix the plot"
"""

from __future__ import annotations

import asyncio
import copy
import os
import shlex
import time

from ._errors import ON_WINDOWS, SimplyCommandError, TimeLimitError, choice_error, missing_word_error, own_words, suggest
from ._options import OptionStyle, as_word
from ._running import Plan, RunningCommand, Settings, describe_plans, find_program
from .result import Result

CONTAINER_TOOLS = ["docker", "podman", "apptainer", "singularity"]
CONDA_TOOLS = ["conda", "mamba", "micromamba"]
PRIORITIES = ["normal", "low"]


class _Runnable:
    """The words shared by a Program and a Pipeline: settings for running, and running."""

    def __init__(self):
        self._time_limit: float | None = None
        self._live = False
        self._stop_if_it_fails = True
        self._accepted = frozenset({0})
        self._encoding: str | None = None
        self._in_terminal = False
        self._pseudo_terminal = False
        self._keep_input_open = False
        self._on_line = None
        self._on_error_line = None
        self._keep_output = True
        self._tries = 1
        self._wait_between = 0.0

    # ------------------------------------------------------------ how to run
    def set_time_limit(self, seconds: float | None):
        """Stop the command if it runs longer than this many seconds (None: no limit)."""
        if seconds is not None and seconds <= 0:
            raise SimplyCommandError("The time limit must be more than 0 seconds (or None for no limit).")
        self._remember()
        self._time_limit = seconds
        return self

    def show_output_while_running(self):
        """Print what the command writes as it writes it (good for long tools). The result still keeps it."""
        self._remember()
        self._live = True
        return self

    def hide_output_while_running(self):
        """Run quietly and keep the output only in the result (the default)."""
        self._remember()
        self._live = False
        return self

    def keep_going_if_it_fails(self):
        """Do not raise an error when the command fails; the result then says .worked = False."""
        self._remember()
        self._stop_if_it_fails = False
        return self

    def stop_if_it_fails(self):
        """Raise CommandFailedError when the command fails (the default)."""
        self._remember()
        self._stop_if_it_fails = True
        return self

    def accept_exit_codes(self, *codes: int):
        """Count these exit codes as "worked" too: accept_exit_codes(0, 1) for grep, which ends with 1
        when it finds nothing."""
        if not codes or not all(isinstance(c, int) for c in codes):
            raise SimplyCommandError("Give the exit codes as whole numbers, for example accept_exit_codes(0, 1).")
        self._remember()
        self._accepted = frozenset(codes)
        return self

    def try_again_if_it_fails(self, times: int = 3, wait: float = 5):
        """Run the command again if it fails (or reaches its time limit), up to `times` tries in all,
        waiting `wait` seconds between tries. Good for downloads and busy servers."""
        if int(times) < 1:
            raise SimplyCommandError("times= is the number of tries in all, so it must be 1 or more.")
        self._remember()
        self._tries, self._wait_between = int(times), float(wait)
        return self

    def use_text_encoding(self, name: str):
        """Read the program's output in this text encoding, such as "latin-1" or "cp1252".
        Without it, UTF-8 is tried first and then this computer's own encoding."""
        "".encode(name)  # an unknown name raises LookupError here, before anything runs
        self._remember()
        self._encoding = name
        return self

    def run_in_this_terminal(self):
        """Let the program use this terminal directly: it can ask questions, ask for a password and draw
        progress bars. Its output is then not kept in the result."""
        self._remember()
        self._in_terminal = True
        return self

    def run_in_pseudo_terminal(self):
        """Run the program in a pretend terminal that Python reads and types into, for programs that only
        ask questions or show prompts when they think a person is watching (like pexpect).

        Use it with start_in_background, then running.wait_for_text("Password:") and running.send_text(...).
        On Windows it needs the pywinpty package (pip install "simplycommand[terminal]").
        """
        self._remember()
        self._pseudo_terminal = True
        return self

    def keep_input_open(self):
        """Keep the program's input open after it starts, so you can type into it from Python with
        running.send_text(...) (use it with start_in_background)."""
        self._remember()
        self._keep_input_open = True
        return self

    def do_with_each_line(self, function, from_errors: bool = False, keep_output: bool = True):
        """Call your own function with each line the program writes, as soon as it writes it.

        from_errors=True does it for the error stream instead (where many tools write progress).
        keep_output=False does not keep the output in the result (for very big outputs).
        """
        if not callable(function):
            raise SimplyCommandError("do_with_each_line needs a function, for example do_with_each_line(print).")
        self._remember()
        if from_errors:
            self._on_error_line = function
        else:
            self._on_line, self._keep_output = function, keep_output
        return self

    # ------------------------------------------------------------ look at it
    def get_command_line(self) -> str:
        """The command as you would type it in the terminal, with quotes where needed."""
        return describe_plans(self._plans())

    def show_command(self):
        """Print the command as you would type it in the terminal (nothing is run)."""
        print(self.get_command_line())
        return self

    # ------------------------------------------------------------ run it
    def run(self, *words, **options) -> Result:
        """Run the command and wait until it is done. Gives a Result.

        Words and options given here are added for this run only:
        samtools.run("sort", "in.bam", o="out.bam", threads=4).
        """
        plans = self._plans(words, options)
        for attempt in range(1, self._tries + 1):
            last_try = attempt == self._tries
            settings = self._settings(stop_if_it_fails=self._stop_if_it_fails if last_try else False)
            try:
                result = RunningCommand(plans, settings).wait_until_done()
            except TimeLimitError:
                if last_try:
                    raise
                time.sleep(self._wait_between)
                continue
            result.attempts = attempt
            if result.worked or last_try:
                return result
            time.sleep(self._wait_between)
        raise AssertionError("not reached")  # pragma: no cover

    def __call__(self, *words, **options) -> Result:
        return self.run(*words, **options)

    async def run_async(self, *words, **options) -> Result:
        """The same as run(), for async code: result = await program.run_async(...)."""
        return await asyncio.to_thread(self.run, *words, **options)

    def start_in_background(self, *words, **options) -> RunningCommand:
        """Start the command and carry on at once. Gives a RunningCommand to check on, talk to, wait for or stop."""
        return RunningCommand(self._plans(words, options), self._settings())

    def send_output_to(self, other: "Program") -> "Pipeline":
        """Pipe this command's output into another program (like | in the terminal). Gives a new Pipeline."""
        return Pipeline([*self._stages(), *_stages_of(other)], settings_from=self)

    def __or__(self, other):
        return self.send_output_to(other)

    def send_errors_to(self, other: "Program") -> "Pipeline":
        """Pipe this command's error stream (not its output) into another program, like 2>&1 >/dev/null |.
        Its normal output goes to the file set with save_output_to, or is dropped."""
        stages = self._stages()
        stages[-1] = stages[-1].copy()
        stages[-1]._errors_to_next = True
        return Pipeline([*stages, *_stages_of(other)], settings_from=self)

    def _settings(self, **changes) -> Settings:
        values = dict(live=self._live, time_limit=self._time_limit, stop_if_it_fails=self._stop_if_it_fails,
                      accepted_codes=self._accepted, encoding=self._encoding, in_terminal=self._in_terminal,
                      pseudo_terminal=self._pseudo_terminal, keep_input_open=self._keep_input_open, on_line=self._on_line,
                      on_error_line=self._on_error_line, keep_output=self._keep_output)
        values.update(changes)
        return Settings(**values)

    def _copy_settings_from(self, other: "_Runnable") -> None:
        for name in ("_time_limit", "_live", "_stop_if_it_fails", "_accepted", "_encoding", "_in_terminal",
                     "_pseudo_terminal", "_keep_input_open", "_on_line", "_on_error_line", "_keep_output", "_tries", "_wait_between"):
            setattr(self, name, getattr(other, name))

    def _remember(self) -> None:
        pass


class Program(_Runnable):
    """One command-line program, with the words and options you have added to it.

    Make one with scmd.program("samtools"). To wrap a tool in a class of your own:

        class Samtools(scmd.Program):
            program_name = "samtools"

            def sort_file(self, bam, into, threads=1):
                return self.run("sort", bam, o=into, threads=threads)
    """

    program_name: str | None = None
    option_style: str = "--long-name"

    def __init__(self, name=None, *words, option_style: str | None = None, **options):
        super().__init__()
        name = name if name is not None else type(self).program_name
        if name is None:
            raise SimplyCommandError('A program needs a name, for example scmd.program("git"), '
                                     'or program_name = "git" in your own class.')
        self._name = as_word(name)
        self._style = OptionStyle(option_style or type(self).option_style)
        self._parts: list[tuple] = []  # ("words", [...]) or ("option", flag, [...])
        self._folder: str | None = None
        self._environment: dict = {}
        self._clean_environment = False
        self._keep_variables: tuple = ()
        self._python_environment: str | None = None
        self._input_text = None
        self._input_file: str | None = None
        self._output_file: str | None = None
        self._append_output = False
        self._errors_file: str | None = None
        self._errors_into_output = False
        self._errors_to_next = False
        self._output_also_keep = False
        self._errors_also_keep = False
        self._remove_variables: tuple = ()
        self._hide_window = False
        self._low_priority = False
        self._own_group = False
        self._program_file: str | None = None
        self._user = self._group = self._umask = None
        self._pass_fds: tuple = ()
        self._before_start = None
        self._memory_limit_mb: float | None = None
        self._cpu_limit_seconds: float | None = None
        self._popen_extra: dict = {}
        self._as_admin = False
        self._conda: tuple | None = None       # (tool, environment)
        self._container: tuple | None = None   # (tool, image, mount folder)
        self._computer: dict | None = None     # ssh address and options
        self._history: list[dict] = []
        if words:
            self.add_words(*words)
        if options:
            self.add_options(**options)
        self._history.clear()

    # ------------------------------------------------------------ add and remove
    def add_words(self, *words) -> "Program":
        """Add plain words after the program name: subcommands, file names, values.

        git.add_words("commit") · samtools.add_words("sort", "reads.bam")
        """
        self._remember()
        self._parts.append(("words", [as_word(w) for w in words]))
        return self

    def add_option(self, name, *values) -> "Program":
        """Add an option with its value(s). The name is written in the program's option style.

        add_option("threads", 4) -> --threads 4 · add_option("o", "out.bam") -> -o out.bam ·
        add_option("--in", "x") is used as written · add_option("files", "a", "b") -> --files a b
        """
        if not values:
            raise SimplyCommandError(f'add_option("{name}") needs a value. '
                                     f'For an option without a value use add_switch("{name}").')
        self._remember()
        self._parts.append(("option", self._style.flag(name), self._style.words(name, *values)))
        return self

    def add_switch(self, *names) -> "Program":
        """Add options that have no value, such as --verbose or -f: add_switch("verbose", "f")."""
        self._remember()
        for name in names:
            self._parts.append(("option", self._style.flag(name), [self._style.flag(name)]))
        return self

    def add_options(self, **options) -> "Program":
        """Add many options at once: add_options(threads=4, o="out.bam", verbose=True).

        True makes a switch, False or None leaves the option out, a list repeats it,
        and in_="x" becomes --in (a trailing _ lets you use Python words such as in, for, import).
        """
        self._remember()
        for name, value in options.items():
            self._parts.append(("option", self._style.flag(name), self._style.words(name, value)))
        return self

    def remove_option(self, name) -> "Program":
        """Take an option (and its values) out again: remove_option("threads")."""
        flag = self._style.flag(name)
        if not any(part[0] == "option" and part[1] == flag for part in self._parts):
            have = [part[1] for part in self._parts if part[0] == "option"]
            lines = [f'The program has no option "{flag}" to remove.']
            guess = suggest(flag, have, n=1)
            if guess:
                lines.append(f'Did you mean "{guess[0]}"?')
            lines.append("Options it has: " + (", ".join(have) if have else "none yet"))
            raise SimplyCommandError("\n".join(lines))
        self._remember()
        self._parts = [part for part in self._parts if not (part[0] == "option" and part[1] == flag)]
        return self

    def remove_words(self, *words) -> "Program":
        """Take plain words out again: remove_words("reads.bam")."""
        self._remember()
        gone = {as_word(w) for w in words}
        self._parts = [("words", [w for w in part[1] if w not in gone]) if part[0] == "words" else part
                       for part in self._parts]
        return self

    def use_option_style(self, example: str) -> "Program":
        """Write option names the way this tool does. Show one example from its help:

        "--long-name" (the default) · "-long_name" (BLAST) · "--long-name=value" · "/name" (old Windows tools)
        """
        self._remember()
        self._style = OptionStyle(example)
        return self

    def undo(self) -> "Program":
        """Take back the last change to the program."""
        if not self._history:
            raise SimplyCommandError("There is nothing to undo.")
        self.__dict__.update(self._history.pop())
        return self

    # ------------------------------------------------------------ where and how
    def set_folder(self, folder) -> "Program":
        """Run the program in this folder (its working directory). On another computer, a folder there."""
        self._remember()
        self._folder = None if folder is None else os.fspath(folder)
        return self

    def set_environment(self, **variables) -> "Program":
        """Set environment variables for the program only: set_environment(OMP_NUM_THREADS=4)."""
        self._remember()
        self._environment = {**self._environment, **{k: as_word(v) for k, v in variables.items()}}
        return self

    def use_clean_environment(self, keep=("PATH", "HOME", "USERPROFILE", "LANG")) -> "Program":
        """Start the program with almost no environment variables, only those in keep= and the ones set
        with set_environment (plus the few Windows needs to start a program). Good for reproducible runs."""
        self._remember()
        self._clean_environment = True
        self._keep_variables = tuple(keep)
        return self

    def use_input_text(self, text) -> "Program":
        """Give the program this text, as if typed into it (its standard input)."""
        self._remember()
        self._input_text, self._input_file = text, None
        return self

    def use_input_file(self, file_name) -> "Program":
        """Give the program this file as its input (like < file.txt in the terminal)."""
        self._remember()
        self._input_file, self._input_text = os.fspath(file_name), None
        return self

    def save_output_to(self, file_name, add_to_end: bool = False, also_keep: bool = False) -> "Program":
        """Write the program's output straight into a file (like > file.txt); add_to_end=True is like >>.

        Good for big outputs: they go to the file without being kept in memory.
        also_keep=True also keeps it in the result (like tee).
        """
        self._remember()
        self._output_file, self._append_output = os.fspath(file_name), add_to_end
        self._output_also_keep = also_keep
        return self

    def save_errors_to(self, file_name, also_keep: bool = False) -> "Program":
        """Write the program's error stream (often its progress messages) into a file (like 2> log.txt).
        also_keep=True also keeps it in the result."""
        self._remember()
        self._errors_file = os.fspath(file_name)
        self._errors_also_keep = also_keep
        return self

    def remove_environment_variable(self, *names) -> "Program":
        """Run the program without these environment variables: remove_environment_variable("PYTHONPATH")."""
        self._remember()
        self._remove_variables = (*self._remove_variables, *map(str, names))
        return self

    def add_files_matching(self, pattern, in_folder=None) -> "Program":
        """Add the names of all files matching a pattern, sorted, as a shell would for *.fa:
        add_files_matching("*.fastq.gz") · add_files_matching("raw/**/*_R1.fq.gz") (** is any folders).
        The names are relative to in_folder= (or the program's folder) and are found now."""
        import glob

        base = os.fspath(in_folder) if in_folder is not None else (self._folder or ".")
        found = sorted(glob.glob(os.fspath(pattern), root_dir=base, recursive=True))
        if not found:
            raise SimplyCommandError(f'No files match "{pattern}" in the folder "{os.path.abspath(base)}".')
        self._remember()
        self._parts.append(("words", found))
        return self

    def set_memory_limit(self, megabytes: float | None) -> "Program":
        """Do not let the program use more than this much memory (in MB); past it, asking for more fails
        (None: no limit)."""
        if megabytes is not None and megabytes <= 0:
            raise SimplyCommandError("The memory limit must be more than 0 MB (or None for no limit).")
        self._remember()
        self._memory_limit_mb = megabytes
        return self

    def set_cpu_time_limit(self, seconds: float | None) -> "Program":
        """Stop the program when it has used this much CPU time (time spent computing, not waiting)."""
        if seconds is not None and seconds <= 0:
            raise SimplyCommandError("The CPU time limit must be more than 0 seconds (or None for no limit).")
        self._remember()
        self._cpu_limit_seconds = seconds
        return self

    def start_in_own_group(self) -> "Program":
        """Start the program in a process group of its own: Ctrl+C in Python's terminal does not reach it,
        and on Windows it can be sent "ctrl+break"."""
        self._remember()
        self._own_group = True
        return self

    def use_program_file(self, path) -> "Program":
        """Run this program file, while the program still sees its first word as its own name
        (subprocess's executable=). Some tools, such as busybox, act by the name they are called by."""
        self._remember()
        self._program_file = os.fspath(path)
        return self

    def run_as_user(self, user, group=None) -> "Program":
        """Run the program as another user (and group), by name or number. Linux and macOS only; Python
        must be allowed to switch user (usually it runs as root)."""
        self._remember()
        self._user, self._group = user, group
        return self

    def run_as_administrator(self) -> "Program":
        """Run the program with administrator rights: sudo on Linux and macOS (and on another computer),
        the Windows "Run as administrator" prompt on Windows. On Windows the output cannot be kept,
        only the exit code; use save_output_to inside the program's own options if it has one."""
        self._remember()
        self._as_admin = True
        return self

    def set_umask(self, mask: int) -> "Program":
        """Set the umask for files the program makes, for example 0o027 (Linux and macOS only)."""
        self._remember()
        self._umask = int(mask)
        return self

    def share_open_files(self, *descriptors: int) -> "Program":
        """Let the program use these open file descriptors of Python's (subprocess's pass_fds; Linux and macOS)."""
        self._remember()
        self._pass_fds = tuple(int(d) for d in descriptors)
        return self

    def do_before_start(self, function) -> "Program":
        """Call your own function in the new process just before the program starts (subprocess's
        preexec_fn; Linux and macOS). Keep it small: it runs in a copy of Python at a delicate moment."""
        if not callable(function):
            raise SimplyCommandError("do_before_start needs a function.")
        self._remember()
        self._before_start = function
        return self

    def use_subprocess_settings(self, **settings) -> "Program":
        """Give subprocess.Popen any setting simplycommand has no word for: use_subprocess_settings(bufsize=0,
        startupinfo=info). This is the door to everything subprocess can do."""
        import inspect
        import subprocess

        known = [p for p in inspect.signature(subprocess.Popen.__init__).parameters if p not in ("self", "args")]
        ours = {"stdin": "use_input_file / use_input_text", "stdout": "save_output_to", "stderr": "save_errors_to",
                "cwd": "set_folder", "env": "set_environment", "shell": "scmd.run_in_shell",
                "executable": "use_program_file", "preexec_fn": "do_before_start", "pass_fds": "share_open_files",
                "user": "run_as_user", "group": "run_as_user", "umask": "set_umask", "text": "use_text_encoding",
                "encoding": "use_text_encoding", "errors": "use_text_encoding",
                "universal_newlines": "use_text_encoding"}
        for name in settings:
            if name in ours:
                raise SimplyCommandError(f"{name}= has its own word in simplycommand: {ours[name]}.")
            if name not in known:
                guess = suggest(name, known, n=1)
                raise SimplyCommandError(f"subprocess.Popen has no setting called {name}=."
                                         + (f" Did you mean {guess[0]}=?" if guess else ""))
        self._remember()
        self._popen_extra = {**self._popen_extra, **settings}
        return self

    def start_and_leave_running(self, *words, **options) -> int:
        """Start the program so that it keeps running after Python ends (a server, a long job), and give its
        process id. Its output goes only to files set with save_output_to and save_errors_to."""
        from ._running import start_detached

        return start_detached(self._plan(words, options))

    def put_errors_into_output(self) -> "Program":
        """Mix the error stream into the output, in the order they are written (like 2>&1)."""
        self._remember()
        self._errors_into_output = True
        return self

    def set_priority(self, level: str) -> "Program":
        """Run the program at "low" priority, so the computer stays quick for other work, or "normal"."""
        if level not in PRIORITIES:
            raise choice_error("set_priority", "level", level, PRIORITIES)
        self._remember()
        self._low_priority = level == "low"
        return self

    def hide_window(self) -> "Program":
        """On Windows, do not open a console window for the program (nothing changes elsewhere)."""
        self._remember()
        self._hide_window = True
        return self

    # ------------------------------------------------------------ other places to run
    def use_python_environment(self, folder) -> "Program":
        """Run the program from a Python virtual environment (venv) folder, as if it were activated."""
        folder = os.path.abspath(os.fspath(folder))
        scripts = os.path.join(folder, "Scripts" if ON_WINDOWS else "bin")
        if not os.path.isdir(scripts):
            raise SimplyCommandError(f'"{folder}" does not look like a Python environment: '
                                     f'it has no {os.path.basename(scripts)} folder.')
        self._remember()
        self._python_environment = folder
        return self

    def use_conda_environment(self, name, using: str = "conda") -> "Program":
        """Run the program inside a conda environment: use_conda_environment("bioinfo").

        A folder works too (use_conda_environment("envs/qc")). using="mamba" or "micromamba" for those tools.
        """
        if using not in CONDA_TOOLS:
            raise choice_error("use_conda_environment", "using", using, CONDA_TOOLS)
        self._remember()
        self._conda = (using, os.fspath(name))
        return self

    def use_container(self, image: str, using: str = "docker", share_folder: bool = True) -> "Program":
        """Run the program inside a container image: use_container("biocontainers/samtools:1.19").

        The program's folder (or the current one) is shared with the container as /work, so file names
        in that folder work as they are. using= "docker" (the default), "podman", "apptainer" or "singularity".
        """
        if using not in CONTAINER_TOOLS:
            raise choice_error("use_container", "using", using, CONTAINER_TOOLS)
        self._remember()
        self._container = (using, str(image), share_folder)
        return self

    def set_computer(self, address: str | None, port: int | None = None, key_file=None,
                     using: str = "ssh") -> "Program":
        """Run the program on another computer over ssh: set_computer("me@server.uni.no").

        Input files given with use_input_file are sent from this computer and output files saved with
        save_output_to are written on this one; set_folder is a folder on the other computer.
        set_computer(None) runs it here again. ssh must be able to log in without a password (a key).
        """
        self._remember()
        self._computer = None if address is None else {"address": str(address), "port": port,
                                                        "key_file": None if key_file is None else os.fspath(key_file),
                                                        "using": using}
        return self

    # ------------------------------------------------------------ new programs from this one
    def copy(self) -> "Program":
        """A copy to change without changing this one."""
        new = copy.copy(self)
        new._parts = list(self._parts)
        new._environment = dict(self._environment)
        new._history = []
        return new

    def make_subcommand(self, *words) -> "Program":
        """A new program with these words added, leaving this one as it is: git.make_subcommand("commit").

        git.commit is a short way to write the same (underscores become dashes: git.cherry_pick).
        """
        return self.copy().add_words(*words)

    # ------------------------------------------------------------ look at it
    def get_command_words(self, *words, **options) -> list[str]:
        """The command as a list of words, the way subprocess wants it (with any ssh, conda or container
        words around it)."""
        return self._plan(words, options).words

    def is_installed(self) -> bool:
        """True if the program can be found on this computer."""
        return find_program(self._name, self._local_environment() or None) is not None

    def find_where_installed(self) -> str | None:
        """Say where the program is on this computer, and give its full path (None if not found)."""
        place = find_program(self._name, self._local_environment() or None)
        print(f'"{self._name}" is at {place}' if place else
              f'"{self._name}" is not installed here, or its folder is not on the PATH.')
        return place

    @property
    def name(self) -> str:
        """The name of the program (the first word of the command)."""
        return self._name

    def __repr__(self) -> str:
        return f"Program: {self.get_command_line()}"

    # ------------------------------------------------------------ inside
    def _remember(self) -> None:
        state = {k: v for k, v in self.__dict__.items() if k != "_history"}
        state["_parts"] = list(self._parts)
        state["_environment"] = dict(self._environment)
        self._history.append(state)

    def _own_words(self, words=(), options=None) -> list[str]:
        result = [self._name]
        for part in self._parts:
            result += part[-1]
        result += [as_word(w) for w in words]
        for name, value in (options or {}).items():
            result += self._style.words(name, value)
        return result

    def _local_environment(self) -> dict:
        env = dict(self._environment)
        if self._python_environment:
            scripts = os.path.join(self._python_environment, "Scripts" if ON_WINDOWS else "bin")
            env["PATH"] = scripts + os.pathsep + env.get("PATH", os.environ.get("PATH", ""))
            env["VIRTUAL_ENV"] = self._python_environment
        return env

    def _base_plan(self, command, folder, environment) -> Plan:
        return Plan(command, folder=folder, environment=environment, clean_environment=self._clean_environment,
                    keep_variables=self._keep_variables, remove_variables=self._remove_variables,
                    input_text=self._input_text, input_file=self._input_file, output_file=self._output_file,
                    append_output=self._append_output, output_also_keep=self._output_also_keep,
                    errors_file=self._errors_file, errors_also_keep=self._errors_also_keep,
                    errors_into_output=self._errors_into_output, errors_to_next=self._errors_to_next,
                    hide_window=self._hide_window, low_priority=self._low_priority, own_group=self._own_group,
                    program_file=self._program_file, user=self._user, group=self._group, umask=self._umask,
                    pass_fds=self._pass_fds, before_start=self._before_start,
                    memory_limit_mb=self._memory_limit_mb, cpu_limit_seconds=self._cpu_limit_seconds,
                    popen_extra=dict(self._popen_extra))

    def _admin_words(self, command, folder) -> list[str]:
        if self._computer or not ON_WINDOWS:
            return ["sudo", *command]
        import subprocess

        def quoted(text):
            return "'" + str(text).replace("'", "''") + "'"

        found = find_program(command[0], self._local_environment() or None) or command[0]
        script = f"$p = Start-Process -FilePath {quoted(found)}"
        if command[1:]:
            script += f" -ArgumentList {quoted(subprocess.list2cmdline(command[1:]))}"
        if folder:
            script += f" -WorkingDirectory {quoted(os.path.abspath(folder))}"
        script += " -Verb RunAs -Wait -PassThru; exit $p.ExitCode"
        return ["powershell", "-NoProfile", "-Command", script]

    def _plan(self, words=(), options=None) -> Plan:
        command = self._own_words(words, options)
        environment = self._local_environment()
        folder = self._folder
        if self._conda:
            tool, env_name = self._conda
            where = ["-p", env_name] if os.sep in env_name or "/" in env_name else ["-n", env_name]
            command = [tool, "run", *([] if tool == "micromamba" else ["--no-capture-output"]), *where, *command]
        if self._container:
            command, folder = self._container_words(command, environment, folder)
            environment = {}
        if self._as_admin:
            command = self._admin_words(command, folder)
        if self._computer:
            command = self._remote_words(command, environment, folder)
            environment, folder = {}, None
        return self._base_plan(command, folder, environment)

    def _container_words(self, command, environment, folder):
        tool, image, share = self._container
        if self._computer:
            shared = folder or "."  # a folder on the other computer
        else:
            shared = os.path.abspath(folder or os.getcwd())
        env_words = []
        for key, value in environment.items():
            if key in ("PATH", "VIRTUAL_ENV"):
                continue
            env_words += (["-e", f"{key}={value}"] if tool in ("docker", "podman") else ["--env", f"{key}={value}"])
        if tool in ("docker", "podman"):
            share_words = ["-v", f"{shared}:/work", "-w", "/work"] if share else []
            return [tool, "run", "--rm", "-i", *share_words, *env_words, image, *command], folder
        share_words = ["--bind", f"{shared}:/work", "--pwd", "/work"] if share else []
        return [tool, "exec", *share_words, *env_words, image, *command], folder

    def _remote_words(self, command, environment, folder) -> list[str]:
        c = self._computer
        line = shlex.join(command)  # the other computer reads it with its own (POSIX) shell
        variables = {k: v for k, v in environment.items() if k not in ("PATH", "VIRTUAL_ENV")}
        if variables:
            line = "env " + " ".join(shlex.quote(f"{k}={v}") for k, v in variables.items()) + " " + line
        if folder and not self._container:
            line = f"cd {shlex.quote(folder)} && {line}"
        words = [c["using"]]
        if c["port"]:
            words += ["-p", str(c["port"])]
        if c["key_file"]:
            words += ["-i", c["key_file"]]
        return [*words, c["address"], line]

    def _plans(self, words=(), options=None) -> list[Plan]:
        return [self._plan(words, options)]

    def _stages(self) -> list["Program"]:
        return [self]

    def __getattr__(self, name):
        """git.status -> the program "git status" (a new program; call it to run it)."""
        if name.startswith("_"):
            raise AttributeError(name)
        if suggest(name, own_words(self), n=2, cutoff=0.8):  # most likely a typo of one of our own words
            raise missing_word_error("program", name, own_words(self))
        return self.make_subcommand(name.replace("_", "-"))


SHELLS = ["cmd", "powershell", "pwsh", "sh", "bash", "zsh"]


class ShellLine(Program):
    """A line run by a shell, for shell words such as dir and echo, and for | > && in one line."""

    def __init__(self, line: str, shell: str | None = None):
        super().__init__("shell")
        if shell is not None and shell not in SHELLS:
            raise choice_error("run_in_shell", "shell", shell, SHELLS)
        self._line = str(line)
        self._shell = shell

    def _plan(self, words=(), options=None) -> Plan:
        if words or options:
            raise SimplyCommandError("Write the whole line in scmd.run_in_shell(\"...\"); it takes no extra words.")
        plan = self._base_plan([], self._folder, self._local_environment())
        if self._shell is None or (self._shell == "cmd" and ON_WINDOWS):
            plan.shell_line = self._line  # the computer's own shell
        elif self._shell == "cmd":
            raise SimplyCommandError('shell="cmd" is only on Windows. Use shell="sh" or "bash" here.')
        elif self._shell in ("powershell", "pwsh"):
            plan.words = [self._shell, "-NoProfile", "-Command", self._line]
        else:
            plan.words = [self._shell, "-c", self._line]
        return plan

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise missing_word_error("shell line", name, own_words(self))


class Pipeline(_Runnable):
    """Programs joined by pipes: the output of each goes into the next (like a | b | c).

        lines = scmd.program("zcat", "reads.fq.gz") | scmd.program("wc", "-l")
        lines.run().output
    """

    def __init__(self, programs, settings_from: _Runnable | None = None):
        super().__init__()
        self._programs = [p.copy() for p in programs]
        if len(self._programs) < 2:
            raise SimplyCommandError("A pipeline joins at least two programs: a.send_output_to(b).")
        self._copy_settings_from(settings_from or self._programs[-1])

    def _plans(self, words=(), options=None) -> list[Plan]:
        if words or options:
            raise SimplyCommandError("Add words to one of the programs before joining them; "
                                     "a pipeline's run() takes no extra words.")
        return [p._plan() for p in self._programs]

    def _stages(self) -> list[Program]:
        return list(self._programs)

    def get_programs(self) -> list[Program]:
        """The programs in the pipeline, in order."""
        return list(self._programs)

    def __repr__(self) -> str:
        return f"Pipeline: {self.get_command_line()}"

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise missing_word_error("pipeline", name, own_words(self))


def _stages_of(other) -> list[Program]:
    if isinstance(other, (Program, Pipeline)):
        return other._stages()
    if isinstance(other, str):
        raise SimplyCommandError(f'Pipe into a program, not text: send_output_to(scmd.program("{other}")).')
    raise SimplyCommandError(f"Pipe into a program made with scmd.program(...), not a {type(other).__name__}.")
