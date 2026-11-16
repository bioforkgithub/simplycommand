"""Step 6: a command-line program that runs other programs, the other half of simplycommand.

Try in the terminal:
    python 06_running_other_programs.py versions python git
    python 06_running_other_programs.py timed -- python -c "print(sum(range(10**7)))"
    python 06_running_other_programs.py timed --log runs.log -- git status
    python 06_running_other_programs.py count-lines -- python -c "print('a'); print('b')"
    python 06_running_other_programs.py together 3

(The -- tells the program that the words after it belong to the other program, even if
they start with a dash.)

What it shows:
    scmd.program(name)                    a program as an object
    .keep_going_if_it_fails()             a failure gives result.worked = False instead of an error
    .set_time_limit(...)                  stop it if it runs too long
    result.output, result.seconds         what it wrote and how long it took
    a | b                                 a pipe, as in the terminal
    scmd.run_together([...], at_most=2)   many programs at once
    scmd.start_log_in("runs.log")         a record of every command that was run
"""

import sys

import simplycommand as scmd


class Runner(scmd.CommandLineProgram):
    """Run other programs and say how it went."""

    def versions(self, *programs: str):
        """Show the version of each program, or say that it is missing."""
        lines = []
        for name in programs:
            prog = scmd.program(name)
            if not prog.is_installed():
                lines.append(f"{name:<10} not installed")
                continue
            result = prog.keep_going_if_it_fails().set_time_limit(20).run("--version")
            first = (result.get_output_lines() or result.get_error_lines() or ["?"])[0]
            lines.append(f"{name:<10} {first}")
        return lines

    def timed(self, *command: str, log: str | None = None, limit: float = 600):
        """Run any command, then say whether it worked and how long it took.
        command: the program and its words, after --
        log: also write a record of the run into this file
        limit: stop it after this many seconds
        """
        if not command:
            raise scmd.SimplyCommandError("Give a command after --, for example: timed -- git status")
        if log:
            scmd.start_log_in(log)
        result = scmd.program(*command).keep_going_if_it_fails().set_time_limit(limit).run()
        result.show_output()
        return result.describe(quiet=True)  # one sentence: worked or failed, and how long it took

    def count_lines(self, *command: str):
        """Count the lines a command writes, by piping it into a second program."""
        if not command:
            raise scmd.SimplyCommandError("Give a command after --.")
        counter = scmd.program(sys.executable, "-c", "import sys; print(sum(1 for _ in sys.stdin))")
        pipe = scmd.program(*command) | counter
        return f"{pipe.run().output.strip()} lines"

    def together(self, how_many: int = 4, at_most: int = 2):
        """Run several programs at the same time (here: small Python programs that wait a moment)."""
        jobs = [scmd.program(sys.executable, "-c", f"import time; time.sleep(1); print('job {i} done')")
                for i in range(1, how_many + 1)]
        results = scmd.run_together(jobs, at_most=at_most)
        return [f"{r.output.strip()} after {r.seconds:.1f} s" for r in results]


if __name__ == "__main__":
    Runner.start_from_command_line()
