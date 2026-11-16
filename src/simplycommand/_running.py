"""The engine underneath: starts programs with subprocess.Popen (or a pseudo-terminal), joins pipes,
reads their output while they run, keeps time, memory and CPU limits, measures what they used, stops
whole process trees, sends signals, talks to running programs and builds the Result."""

from __future__ import annotations

import datetime
import locale
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field

from . import _errors
from ._errors import ON_WINDOWS, CommandFailedError, SimplyCommandError, TimeLimitError
from .result import Result, _last_lines

# ---------------------------------------------------------------- settings for the whole session
SETTINGS = {"show_commands": False, "log_file": None}
_LOG_LOCK = threading.Lock()

# Variables a program on Windows needs even in a clean environment, or it may not start at all.
_WINDOWS_NEEDS = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP")
_POSIX_ONLY = {"user": "run_as_user", "group": "run_as_user", "umask": "set_umask",
               "pass_fds": "share_open_files", "before_start": "do_before_start"}


@dataclass
class Plan:
    """One program to start: its words and where and how to run it."""

    words: list[str]
    folder: str | None = None
    environment: dict = field(default_factory=dict)
    clean_environment: bool = False
    keep_variables: tuple = ()
    remove_variables: tuple = ()
    input_text: str | bytes | None = None
    input_file: str | None = None
    output_file: str | None = None
    append_output: bool = False
    output_also_keep: bool = False
    errors_file: str | None = None
    errors_also_keep: bool = False
    errors_into_output: bool = False
    errors_to_next: bool = False
    shell_line: str | None = None  # run this line in the default shell instead of `words`
    hide_window: bool = False
    low_priority: bool = False
    own_group: bool = False
    program_file: str | None = None
    user: str | int | None = None
    group: str | int | None = None
    umask: int | None = None
    pass_fds: tuple = ()
    before_start: object = None
    memory_limit_mb: float | None = None
    cpu_limit_seconds: float | None = None
    popen_extra: dict = field(default_factory=dict)


@dataclass
class Settings:
    """How a whole command (one program or a pipeline) is run and judged."""

    live: bool = False
    time_limit: float | None = None
    stop_if_it_fails: bool = True
    accepted_codes: frozenset = frozenset({0})
    encoding: str | None = None
    in_terminal: bool = False
    pseudo_terminal: bool = False
    keep_input_open: bool = False
    on_line: object = None
    on_error_line: object = None
    keep_output: bool = True


def command_line(words: list[str]) -> str:
    """The words as you would type them in this computer's terminal (with quotes where needed)."""
    if ON_WINDOWS:
        return subprocess.list2cmdline(words)
    import shlex

    return shlex.join(words)


def describe_plans(plans: list[Plan]) -> str:
    line = ""
    for i, plan in enumerate(plans):
        part = plan.shell_line if plan.shell_line is not None else command_line(plan.words)
        if plan.errors_into_output:
            part += " 2>&1"
        if i < len(plans) - 1 and plan.errors_to_next:
            part += f" 2>&1 >{command_line([plan.output_file]) if plan.output_file else ('NUL' if ON_WINDOWS else '/dev/null')}"
        line += part if i == 0 else f" | {part}"
    first, last = plans[0], plans[-1]
    if first.input_file:
        line += f" < {command_line([first.input_file])}"
    if last.output_file:
        arrow = ">>" if last.append_output else ">"
        line += (f" | tee {'-a ' if last.append_output else ''}{command_line([last.output_file])}"
                 if last.output_also_keep else f" {arrow} {command_line([last.output_file])}")
    if last.errors_file and not last.errors_into_output:
        line += f" 2> {command_line([last.errors_file])}"
    return line


def build_environment(plan: Plan) -> dict | None:
    """The environment the program gets, or None for "the same as Python's"."""
    if not plan.environment and not plan.clean_environment and not plan.remove_variables:
        return None
    if plan.clean_environment:
        keep = set(plan.keep_variables) | (set(_WINDOWS_NEEDS) if ON_WINDOWS else set())
        env = {k: v for k, v in os.environ.items() if _same_name(k, keep)}
    else:
        env = os.environ.copy()
    for name in plan.remove_variables:
        for key in [k for k in env if _same_name(k, {name})]:
            del env[key]
    env.update({str(k): str(v) for k, v in plan.environment.items()})
    return env


def _same_name(key: str, names) -> bool:
    return key.upper() in {n.upper() for n in names} if ON_WINDOWS else key in names


def find_program(name: str, environment: dict | None = None) -> str | None:
    """The full path of a program, or None if it cannot be found."""
    path = None
    if environment:
        path = next((v for k, v in environment.items() if k.upper() == "PATH"), "")
    if os.path.dirname(name):  # a path was given
        if os.path.isfile(name):
            return os.path.abspath(name)
        return shutil.which(name)  # adds .exe on Windows if needed
    return shutil.which(name, path=path if environment else None)


def decode(data: bytes, encoding: str | None = None) -> str:
    """Text from bytes: the encoding asked for, or else UTF-8 first and then this computer's own."""
    if encoding:
        text = data.decode(encoding, errors="replace")
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode(locale.getpreferredencoding(False) or "latin-1", errors="replace")
    return text.replace("\r\n", "\n")


def _resolve(plan: Plan, env) -> tuple:
    """(args, shell) for Popen, after finding the program."""
    if plan.shell_line is not None:
        return plan.shell_line, True
    found = find_program(plan.words[0], env) if plan.program_file is None else plan.words[0]
    if found is None:
        path = next((v for k, v in (env or os.environ).items() if k.upper() == "PATH"), None)
        raise _errors.program_not_found_error(plan.words[0], path)
    args = [found, *plan.words[1:]]
    if plan.low_priority and not ON_WINDOWS and shutil.which("nice"):
        args = [shutil.which("nice"), "-n", "10", *args]
    return args, False


def _popen_settings(plan: Plan, *, new_session: bool, pty_slave=None) -> dict:
    """The Popen settings for one plan, apart from its streams."""
    extra: dict = {}
    if ON_WINDOWS:
        for name, word in _POSIX_ONLY.items():
            if getattr(plan, name) not in (None, ()):
                raise SimplyCommandError(f"{word}() works only on Linux and macOS; Windows has no such setting.")
        flags = 0
        if plan.hide_window:
            flags |= subprocess.CREATE_NO_WINDOW
        if plan.low_priority:
            flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
        if plan.own_group:
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        extra["creationflags"] = flags
    else:
        if plan.user is not None:
            extra["user"] = plan.user
        if plan.group is not None:
            extra["group"] = plan.group
        if plan.umask is not None:
            extra["umask"] = plan.umask
        if plan.pass_fds:
            extra["pass_fds"] = tuple(plan.pass_fds)
        steps = []
        if plan.memory_limit_mb and sys.platform == "darwin":
            raise SimplyCommandError("macOS does not let one program limit another's memory, so set_memory_limit "
                                     "cannot work here. set_cpu_time_limit and set_time_limit do work.")
        if plan.memory_limit_mb or plan.cpu_limit_seconds:
            memory, cpu = plan.memory_limit_mb, plan.cpu_limit_seconds

            def limits():
                import resource

                if memory:
                    size = int(memory * 1024 * 1024)
                    resource.setrlimit(resource.RLIMIT_AS, (size, size))
                if cpu:
                    seconds = max(1, int(round(cpu)))
                    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds + 1))
            steps.append(limits)
        if pty_slave is not None:
            def take_terminal():
                import fcntl
                import termios

                fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            steps.append(take_terminal)
        if plan.before_start is not None:
            steps.append(plan.before_start)
        if steps:
            extra["preexec_fn"] = lambda: [step() for step in steps]
        if new_session or plan.own_group or pty_slave is not None:
            extra["start_new_session"] = True  # so the whole tree of processes can be stopped
    if plan.program_file is not None:
        extra["executable"] = plan.program_file
    extra.update(plan.popen_extra)
    return extra


class RunningCommand:
    """A command that has been started. Ask whether it is still running, talk to it, wait for it, or stop it.

        running = scmd.program("bwa").start_in_background("index", "genome.fa")
        running.is_running()
        result = running.wait_until_done()
    """

    def __init__(self, plans: list[Plan], settings: Settings | None = None):
        self._plans = plans
        self._settings = settings or Settings()
        self._line = describe_plans(plans)
        self._folder = os.path.abspath(plans[-1].folder or os.getcwd())
        self._procs: list = []
        self._threads: list[threading.Thread] = []
        self._output = bytearray()
        self._errors: list[bytearray] = []
        self._handles = []
        self._stdin = None
        self._pty_master = None
        self._stopped: str | None = None
        self._result: Result | None = None
        self._callback_error: BaseException | None = None
        self._usage = {"cpu": 0.0, "memory": None, "known": False}
        self._job = None
        self._new_session = not ON_WINDOWS and not self._settings.in_terminal
        if SETTINGS["show_commands"]:
            print(f"> {self._line}", flush=True)
        self._started = time.perf_counter()
        try:
            if self._settings.pseudo_terminal:
                self._start_in_pseudo_terminal()
            else:
                self._start()
        except BaseException:
            self._kill()
            self._close_handles()
            raise

    # ------------------------------------------------------------ starting
    def _make_job(self) -> None:
        if not ON_WINDOWS:
            return
        memory = max((p.memory_limit_mb or 0) for p in self._plans) or None
        cpu = max((p.cpu_limit_seconds or 0) for p in self._plans) or None
        try:
            from ._winjob import Job

            self._job = Job(memory_limit_mb=memory, cpu_limit_seconds=cpu)
        except OSError:
            if memory or cpu:
                raise SimplyCommandError("Windows did not allow a memory or CPU limit here.") from None
            self._job = None

    def _start(self) -> None:
        s = self._settings
        self._make_job()
        previous_out = None
        last = len(self._plans) - 1
        for i, plan in enumerate(self._plans):
            env = build_environment(plan)
            if plan.folder and not os.path.isdir(plan.folder):
                raise SimplyCommandError(f'The folder "{plan.folder}" does not exist, so the command cannot run in it.\n'
                                         f"Command: {command_line(plan.words) if plan.words else plan.shell_line}")
            args, shell = _resolve(plan, env)
            pipe_errors = i < last and plan.errors_to_next

            if i == 0:
                if plan.input_file:
                    stdin = self._open(plan.input_file, "rb")
                elif plan.input_text is not None or s.keep_input_open:
                    stdin = subprocess.PIPE
                else:
                    stdin = None if s.in_terminal else subprocess.DEVNULL
            else:
                stdin = previous_out
            output_tee = None
            if pipe_errors:
                stdout = self._open(plan.output_file, "wb") if plan.output_file else subprocess.DEVNULL
            elif i == last and plan.output_file and not plan.output_also_keep:
                stdout = self._open(plan.output_file, "ab" if plan.append_output else "wb")
            elif i == last and s.in_terminal:
                stdout = None
            else:
                stdout = subprocess.PIPE
                if i == last and plan.output_file:
                    output_tee = self._open(plan.output_file, "ab" if plan.append_output else "wb")
            errors_tee = None
            if pipe_errors:
                stderr = subprocess.PIPE
            elif plan.errors_into_output:
                stderr = subprocess.STDOUT
            elif plan.errors_file and not plan.errors_also_keep:
                stderr = self._open(plan.errors_file, "wb")
            elif s.in_terminal:
                stderr = None
            else:
                stderr = subprocess.PIPE
                if plan.errors_file:
                    errors_tee = self._open(plan.errors_file, "wb")

            proc = subprocess.Popen(args, shell=shell, cwd=plan.folder, env=env, stdin=stdin, stdout=stdout,
                                    stderr=stderr, **_popen_settings(plan, new_session=self._new_session))
            if self._job is not None:
                self._job.add(proc.pid)
            if previous_out is not None:
                previous_out.close()  # so the earlier program hears when the later one stops reading
            self._procs.append(proc)

            errors = bytearray()
            self._errors.append(errors)
            if pipe_errors:
                previous_out = proc.stderr
            else:
                previous_out = proc.stdout
                if proc.stderr is not None:
                    self._read(proc.stderr, errors, sys.stderr, s.on_error_line, True, errors_tee)
            if i == 0 and proc.stdin is not None:
                self._stdin = proc.stdin
                if plan.input_text is not None:
                    data = plan.input_text.encode("utf-8") if isinstance(plan.input_text, str) else plan.input_text
                    if s.keep_input_open:
                        self.send_text(data)
                    else:
                        self._thread(_feed, proc.stdin, data)
            if i == last and proc.stdout is not None:
                self._read(proc.stdout, self._output, sys.stdout, s.on_line, s.keep_output, output_tee)

    def _start_in_pseudo_terminal(self) -> None:
        if len(self._plans) > 1:
            raise SimplyCommandError("A pseudo-terminal runs one program, not a pipeline.")
        plan, s = self._plans[0], self._settings
        env = build_environment(plan)
        if plan.folder and not os.path.isdir(plan.folder):
            raise SimplyCommandError(f'The folder "{plan.folder}" does not exist, so the command cannot run in it.')
        args, shell = _resolve(plan, env)
        if shell:
            args = [os.environ.get("COMSPEC", "cmd.exe"), "/c", args] if ON_WINDOWS else ["/bin/sh", "-c", args]
        if ON_WINDOWS:
            proc = _WindowsTerminalProgram(args, plan.folder, env)
            self._procs.append(proc)
            self._pty_master = proc
            self._thread(self._collect_terminal, lambda: proc.read_bytes(), s.on_line)
        else:
            import pty

            master, slave = pty.openpty()
            try:
                proc = subprocess.Popen(args, cwd=plan.folder, env=env, stdin=slave, stdout=slave, stderr=slave,
                                        **_popen_settings(plan, new_session=True, pty_slave=slave))
            finally:
                os.close(slave)
            self._new_session = True
            self._procs.append(proc)
            self._pty_master = master
            self._thread(self._collect_terminal, lambda: os.read(master, 4096), s.on_line)
        self._errors.append(bytearray())
        if plan.input_text is not None:
            self.send_text(plan.input_text)

    def _open(self, file_name, mode):
        folder = os.path.dirname(os.fspath(file_name))
        if "w" in mode or "a" in mode:
            if folder:
                os.makedirs(folder, exist_ok=True)
        elif not os.path.isfile(file_name):
            raise SimplyCommandError(f'The input file "{file_name}" does not exist.')
        handle = open(file_name, mode)
        self._handles.append(handle)
        return handle

    def _thread(self, target, *args) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _read(self, stream, into: bytearray, echo_to, on_line, keep: bool, tee=None) -> None:
        self._thread(self._collect, stream, into, echo_to if self._settings.live else None, on_line, keep, tee)

    def _handle_line(self, line: bytes, on_line) -> None:
        if on_line is not None and self._callback_error is None:
            try:
                on_line(decode(line, self._settings.encoding).rstrip("\r\n"))
            except BaseException as error:  # noqa: BLE001  (reported after the command ends)
                self._callback_error = error

    def _collect(self, stream, into: bytearray, echo_to, on_line, keep: bool, tee) -> None:
        encoding = self._settings.encoding
        try:
            for line in iter(stream.readline, b""):
                if keep:
                    into.extend(line)
                if tee is not None:
                    tee.write(line)
                if echo_to is not None:
                    echo_to.write(decode(line, encoding))
                    echo_to.flush()
                self._handle_line(line, on_line)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def _collect_terminal(self, read_some, on_line) -> None:
        """Read a pseudo-terminal until it closes; it gives chunks, not lines."""
        pending = b""
        while True:
            try:
                chunk = read_some()
            except (OSError, EOFError):
                break
            if not chunk:
                if not self.is_running():
                    break
                time.sleep(0.01)
                continue
            if self._settings.keep_output:
                self._output.extend(chunk)
            if self._settings.live:
                sys.stdout.write(decode(chunk, self._settings.encoding))
                sys.stdout.flush()
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                self._handle_line(line, on_line)
        if pending:
            self._handle_line(pending, on_line)

    # ------------------------------------------------------------ while it runs
    def is_running(self) -> bool:
        """True while the command is still running."""
        return any(proc.poll() is None for proc in self._procs)

    def get_seconds_so_far(self) -> float:
        """How many seconds the command has been running."""
        if self._result is not None:
            return self._result.seconds
        return time.perf_counter() - self._started

    def get_process_id(self) -> int:
        """The process id (PID) of the program (the first one, for a pipe), as the task manager shows it."""
        return self._procs[0].pid

    def get_output_so_far(self) -> str:
        """The text the command has written up to now, while it is still running."""
        return decode(bytes(self._output), self._settings.encoding)

    def send_text(self, text) -> "RunningCommand":
        """Type text into the running program (its standard input). Needs keep_input_open() on the program
        (or a pseudo-terminal). Add "\\n" to press Enter: running.send_text("yes\\n")."""
        data = text.encode(self._settings.encoding or "utf-8") if isinstance(text, str) else bytes(text)
        if self._pty_master is not None:
            try:
                if ON_WINDOWS:
                    self._pty_master.write_bytes(data.replace(b"\n", b"\r"))
                else:
                    os.write(self._pty_master, data)
            except OSError:
                raise SimplyCommandError("The program is no longer reading its input (it has stopped).") from None
            return self
        if self._stdin is None:
            raise SimplyCommandError("This program's input is not open. Use program.keep_input_open() "
                                     "before start_in_background(), then running.send_text(...).")
        try:
            self._stdin.write(data)
            self._stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            raise SimplyCommandError("The program is no longer reading its input (it has stopped or closed it).") from None
        return self

    def close_input(self) -> "RunningCommand":
        """Tell the running program there is no more input (like pressing Ctrl+D)."""
        if self._pty_master is not None:
            if self.is_running():
                try:
                    self.send_text("\x1a\r" if ON_WINDOWS else "\x04")
                except SimplyCommandError:
                    pass
        elif self._stdin is not None:
            try:
                self._stdin.close()
            except OSError:
                pass
        return self

    def wait_for_text(self, text: str, time_limit: float | None = None) -> bool:
        """Wait until the output contains `text` (for example a prompt). False if the time limit
        passes or the program ends without writing it."""
        deadline = None if time_limit is None else time.perf_counter() + time_limit
        while True:
            if text in self.get_output_so_far():
                return True
            if not self.is_running():
                time.sleep(0.1)  # let the readers catch up with the last lines
                return text in self.get_output_so_far()
            if deadline is not None and time.perf_counter() > deadline:
                return False
            time.sleep(0.02)

    def send_signal(self, name: str) -> "RunningCommand":
        """Send a signal to the program and everything it started: "SIGINT", "SIGTERM", "SIGHUP", "SIGUSR1" ...
        (any name in Python's signal module). On Windows: "ctrl+break" (needs start_in_own_group()),
        "ctrl+c" and "SIGTERM"."""
        key = str(name).strip()
        if ON_WINDOWS:
            low = key.lower()
            for proc in self._procs:
                if proc.poll() is not None:
                    continue
                if low in ("ctrl+break", "sigbreak"):
                    if not any(p.own_group for p in self._plans):
                        raise SimplyCommandError('"ctrl+break" needs program.start_in_own_group() before it starts.')
                    os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
                elif low in ("ctrl+c", "sigint"):
                    os.kill(proc.pid, signal.CTRL_C_EVENT)
                elif low in ("sigterm", "sigkill"):
                    proc.kill()
                else:
                    raise _errors.choice_error("send_signal", "name", name, ["ctrl+break", "ctrl+c", "SIGTERM"])
            return self
        names = sorted(s.name for s in signal.Signals)
        upper = key.upper() if key.upper().startswith("SIG") else "SIG" + key.upper()
        if upper not in names:
            raise _errors.choice_error("send_signal", "name", name, names)
        number = signal.Signals[upper]
        for proc in self._procs:
            if proc.poll() is None:
                try:
                    if self._new_session:
                        os.killpg(proc.pid, number)
                    else:
                        proc.send_signal(number)
                except (ProcessLookupError, PermissionError):
                    pass
        return self

    def stop(self, gently: bool = False, wait: float = 10) -> Result:
        """Stop the command now, with everything it started. The result has what it wrote so far.

        gently=True first asks it to stop (so it can tidy up) and forces it only after `wait` seconds.
        """
        if self.is_running():
            self._stopped = "by you"
            if gently:
                self._kill(force=False)
                deadline = time.perf_counter() + wait
                while self.is_running() and time.perf_counter() < deadline:
                    time.sleep(0.05)
            self._kill()
        return self.wait_until_done()

    def wait_until_done(self) -> Result:
        """Wait until the command has finished, and give its result.

        A command that failed raises CommandFailedError, unless the program was told
        keep_going_if_it_fails(); then the result says .worked = False.
        """
        if self._result is None:
            self._result = self._finish()
        result = self._result
        if self._callback_error is not None:
            error, self._callback_error = self._callback_error, None
            raise SimplyCommandError(f"Your function for each line stopped with an error: "
                                     f"{type(error).__name__}: {error}") from error
        if result.stopped == "time limit":
            raise TimeLimitError(f"The command ran longer than its time limit of {self._settings.time_limit:g} "
                                 f"seconds and was stopped:\n    {self._line}\n"
                                 "What it wrote so far is in error.result.", result)
        if result.stopped == "at its CPU time limit":
            limit = max((p.cpu_limit_seconds or 0) for p in self._plans)
            raise TimeLimitError(f"The command used more than its CPU time limit of {limit:g} seconds and was "
                                 f"stopped:\n    {self._line}\nWhat it wrote so far is in error.result.", result)
        if not result.worked and result.stopped is None and self._settings.stop_if_it_fails:
            raise CommandFailedError(_failed_message(result), result)
        return result

    def _wait_one(self, proc, deadline) -> None:
        """Wait for one program; on Linux and macOS with os.wait4, which also says what it used."""
        if ON_WINDOWS or not isinstance(proc, subprocess.Popen) or not hasattr(os, "wait4"):
            proc.wait(timeout=None if deadline is None else max(0.0, deadline - time.perf_counter()))
            return
        pause = 0.001
        while proc.returncode is None:
            try:
                pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
            except ChildProcessError:  # already collected elsewhere
                proc.wait()
                return
            if pid:
                proc.returncode = os.waitstatus_to_exitcode(status)
                rss = usage.ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
                self._usage["cpu"] += usage.ru_utime + usage.ru_stime
                self._usage["memory"] = max(self._usage["memory"] or 0, rss)
                self._usage["known"] = True
                return
            if deadline is not None and time.perf_counter() > deadline:
                raise subprocess.TimeoutExpired(proc.args, 0)
            time.sleep(pause)
            pause = min(pause * 2, 0.05)

    def _finish(self) -> Result:
        limit = self._settings.time_limit
        deadline = None if limit is None else self._started + limit
        try:
            for proc in self._procs:
                try:
                    self._wait_one(proc, deadline)
                except subprocess.TimeoutExpired:
                    self._stopped = "time limit"
                    self._kill()
                    break
            for proc in self._procs:
                proc.wait()
        except KeyboardInterrupt:  # Ctrl+C in Python stops the programs too
            self._kill()
            raise
        for thread in self._threads:
            thread.join(timeout=5)
        seconds = time.perf_counter() - self._started
        self.close_input()
        self._close_terminal()
        self._close_handles()
        cpu = memory = None
        if self._job is not None:
            cpu, memory = self._job.cpu_seconds(), self._job.peak_memory_mb()
            self._job.close()
        elif self._usage["known"]:
            cpu, memory = self._usage["cpu"], self._usage["memory"]
        cpu_limit = max((p.cpu_limit_seconds or 0) for p in self._plans)
        if self._stopped is None and cpu_limit and cpu is not None and cpu >= cpu_limit * 0.98 \
                and any(code != 0 for code in (p.returncode for p in self._procs)):
            self._stopped = "at its CPU time limit"
        enc = self._settings.encoding
        errors = "".join(decode(bytes(e), enc) for e in self._errors)
        last = self._plans[-1]
        result = Result(self._line, [proc.returncode for proc in self._procs], decode(bytes(self._output), enc),
                        errors, seconds, self._folder, output_file=last.output_file, stopped=self._stopped,
                        accepted_codes=self._settings.accepted_codes, output_bytes=bytes(self._output),
                        cpu_seconds=cpu, peak_memory_mb=memory)
        _log(result)
        return result

    def _kill(self, force: bool = True) -> None:
        if force and self._job is not None:
            self._job.stop_all()
        for proc in self._procs:
            if proc.poll() is not None:
                continue
            try:
                if isinstance(proc, _WindowsTerminalProgram):
                    proc.kill()
                elif ON_WINDOWS:
                    # taskkill /T stops the program and every program it started
                    subprocess.run(["taskkill", *(["/F"] if force else []), "/T", "/PID", str(proc.pid)],
                                   capture_output=True)
                    if force and proc.poll() is None:
                        proc.kill()
                elif self._new_session:
                    os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)
                else:
                    proc.kill() if force else proc.terminate()
            except (OSError, ProcessLookupError):
                pass

    def _close_terminal(self) -> None:
        if self._pty_master is None:
            return
        if ON_WINDOWS:
            self._pty_master.close()
        else:
            try:
                os.close(self._pty_master)
            except OSError:
                pass
        self._pty_master = None

    def _close_handles(self) -> None:
        for handle in self._handles:
            try:
                handle.close()
            except OSError:
                pass
        self._handles.clear()

    def __repr__(self) -> str:
        state = "still running" if self.is_running() else "finished"
        return f'The command "{self._line}" is {state} ({self.get_seconds_so_far():.1f} seconds so far).'

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        raise _errors.missing_word_error("running command", name, _errors.own_words(self))


class _WindowsTerminalProgram:
    """A program in a Windows pseudo-console (ConPTY, through the optional pywinpty package),
    with the few parts of Popen the engine uses."""

    def __init__(self, args, folder, env):
        try:
            from winpty import PtyProcess
        except ImportError:
            raise SimplyCommandError("A pseudo-terminal on Windows needs the pywinpty package:\n"
                                     '    pip install "simplycommand[terminal]"   (or: pip install pywinpty)') from None
        # a list, not one string: pywinpty splits a string again and breaks quotes inside it
        self._proc = PtyProcess.spawn(list(args), cwd=folder, env=env, dimensions=(40, 200))
        self.pid = self._proc.pid
        self.args = args
        self.returncode = None

    def read_bytes(self) -> bytes:
        text = self._proc.read(4096)
        return text.encode("utf-8") if isinstance(text, str) else text

    def write_bytes(self, data: bytes) -> None:
        self._proc.write(data.decode("utf-8", errors="replace"))

    def poll(self):
        if self.returncode is None and not self._proc.isalive():
            status = self._proc.exitstatus
            self.returncode = 0 if status is None else int(status)
        return self.returncode

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.perf_counter() + timeout
        while self.poll() is None:
            if deadline is not None and time.perf_counter() > deadline:
                raise subprocess.TimeoutExpired(self.args, timeout)
            time.sleep(0.02)
        return self.returncode

    def kill(self):
        try:
            self._proc.terminate(force=True)
        except Exception:  # noqa: BLE001  (already gone)
            pass

    def close(self):
        try:
            self._proc.close(force=True)
        except Exception:  # noqa: BLE001
            pass


def start_detached(plan: Plan) -> int:
    """Start a program that keeps running after Python ends. Gives its process id."""
    env = build_environment(plan)
    if plan.folder and not os.path.isdir(plan.folder):
        raise SimplyCommandError(f'The folder "{plan.folder}" does not exist, so the command cannot run in it.')
    args, shell = _resolve(plan, env)
    handles = []

    def opened(name, mode):
        if os.path.dirname(name):
            os.makedirs(os.path.dirname(name), exist_ok=True)
        handle = open(name, mode)
        handles.append(handle)
        return handle

    stdin = opened(plan.input_file, "rb") if plan.input_file else subprocess.DEVNULL
    stdout = opened(plan.output_file, "ab" if plan.append_output else "wb") if plan.output_file else subprocess.DEVNULL
    if plan.errors_into_output:
        stderr = subprocess.STDOUT
    else:
        stderr = opened(plan.errors_file, "wb") if plan.errors_file else subprocess.DEVNULL
    extra = _popen_settings(plan, new_session=True)
    if ON_WINDOWS:
        extra["creationflags"] = (extra.get("creationflags", 0) | subprocess.DETACHED_PROCESS
                                  | subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
    try:
        try:
            proc = subprocess.Popen(args, shell=shell, cwd=plan.folder, env=env, stdin=stdin, stdout=stdout,
                                    stderr=stderr, close_fds=True, **extra)
        except PermissionError:
            if not ON_WINDOWS:
                raise
            extra["creationflags"] &= ~0x01000000  # the job we are in does not allow leaving it
            proc = subprocess.Popen(args, shell=shell, cwd=plan.folder, env=env, stdin=stdin, stdout=stdout,
                                    stderr=stderr, close_fds=True, **extra)
    finally:
        for handle in handles:
            handle.close()
    if SETTINGS["show_commands"]:
        print(f"> {describe_plans([plan])} &", flush=True)
    return proc.pid


def _feed(stream, data: bytes) -> None:
    try:
        stream.write(data)
    except (BrokenPipeError, OSError):
        pass  # the program stopped reading; that is its choice
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _failed_message(result: Result) -> str:
    lines = [f"The command failed ({result.describe_exit()}):", f"    {result.command_line}"]
    said = _last_lines(result.errors, 15) or _last_lines(result.output, 15)
    if said:
        lines.append("Its last lines were:")
        lines += ["    " + line for line in said.splitlines()]
    else:
        lines.append("It wrote nothing to explain why.")
    lines.append("To carry on when it fails, use .keep_going_if_it_fails(); the result then says .worked = False.")
    if any(code == 1 for code in result.exit_codes):
        lines.append("(Some tools, such as grep, end with 1 when they find nothing: .accept_exit_codes(0, 1).)")
    return "\n".join(lines)


def _log(result: Result) -> None:
    log_file = SETTINGS["log_file"]
    if not log_file:
        return
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    state = "stopped" if result.stopped else ("worked" if result.worked else f"failed ({result.describe_exit()})")
    used = ""
    if result.cpu_seconds is not None:
        used = f", {result.cpu_seconds:.2f} CPU seconds"
    if result.peak_memory_mb is not None:
        used += f", {result.peak_memory_mb:.0f} MB memory at most"
    with _LOG_LOCK, open(log_file, "a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] in {result.folder}\n{result.command_line}\n"
                     f"  -> {state} in {result.seconds:.2f} seconds{used}\n\n")
