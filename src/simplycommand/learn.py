"""Learning simplycommand: scmd.show_all_words(), scmd.help("add_option") and scmd.show_lesson(1).

The word list is read from the real words and their docstrings, so it cannot go out of date.
Only the grouping (GROUPS) and the lessons are written by hand; a test checks that every
public word is in a group.
"""

from __future__ import annotations

import inspect
import textwrap

from ._errors import SimplyCommandError, suggest

WIDTH = 78

# "scmd.name" is called on scmd; "program.name" on a Program (most also work on a Pipeline);
# "result.name" on a Result; "running.name" on a RunningCommand; "tool.name" on your own CommandLineProgram.
GROUPS = [
    ("Start and run", ["scmd.program", "program.run", "program.run_async", "scmd.run_line", "scmd.run_in_shell",
                       "scmd.make_shell_line", "scmd.find_program", "program.is_installed",
                       "program.find_where_installed"]),
    ("Build a command", ["program.add_words", "program.add_option", "program.add_switch", "program.add_options",
                         "program.add_files_matching", "program.remove_option", "program.remove_words",
                         "program.use_option_style", "program.undo", "program.copy", "program.make_subcommand"]),
    ("Where and how it runs", ["program.set_folder", "program.set_environment", "program.remove_environment_variable",
                               "program.use_clean_environment", "program.set_time_limit", "program.set_priority",
                               "program.hide_window", "program.use_input_text", "program.use_input_file",
                               "program.save_output_to", "program.save_errors_to", "program.put_errors_into_output",
                               "program.use_text_encoding"]),
    ("Limits, users and rights", ["program.set_memory_limit", "program.set_cpu_time_limit",
                                  "program.run_as_administrator", "program.run_as_user", "program.set_umask",
                                  "program.start_in_own_group"]),
    ("Everything else subprocess can do", ["program.use_program_file", "program.share_open_files",
                                           "program.do_before_start", "program.use_subprocess_settings"]),
    ("When it fails", ["program.keep_going_if_it_fails", "program.stop_if_it_fails", "program.accept_exit_codes",
                       "program.try_again_if_it_fails"]),
    ("Watch and talk to it", ["program.show_output_while_running", "program.hide_output_while_running",
                              "program.do_with_each_line", "program.run_in_this_terminal",
                              "program.run_in_pseudo_terminal", "program.keep_input_open"]),
    ("Other places to run", ["program.use_python_environment", "program.use_conda_environment",
                             "program.use_container", "program.set_computer"]),
    ("Look before you run", ["program.show_command", "program.get_command_line", "program.get_command_words"]),
    ("Pipes, background and many at once", ["program.send_output_to", "program.send_errors_to",
                                            "pipeline.get_programs", "program.start_in_background",
                                            "program.start_and_leave_running", "running.is_running",
                                            "running.get_seconds_so_far", "running.get_process_id",
                                            "running.get_output_so_far", "running.wait_for_text",
                                            "running.send_text", "running.close_input", "running.send_signal",
                                            "running.wait_until_done", "running.stop",
                                            "scmd.run_together", "scmd.run_together_async"]),
    ("Results", ["result.worked", "result.exit_code", "result.describe_exit", "result.output", "result.errors",
                 "result.seconds", "result.cpu_seconds", "result.peak_memory_mb", "result.attempts",
                 "result.describe", "result.show_output", "result.show_errors",
                 "result.get_output_lines", "result.get_error_lines", "result.get_output_as_rows",
                 "result.get_output_as_json", "result.get_output_as_bytes", "result.find_lines_with",
                 "result.save_output", "result.save_errors"]),
    ("Files and folders", ["scmd.make_folder", "scmd.copy_file", "scmd.copy_folder", "scmd.move_file",
                           "scmd.move_folder", "scmd.remove_file", "scmd.remove_folder", "scmd.find_files",
                           "scmd.find_size_of", "scmd.find_free_space", "scmd.get_file_dates",
                           "scmd.get_current_folder", "scmd.set_current_folder", "scmd.make_temporary_folder",
                           "scmd.make_temporary_file", "scmd.wait_for_change_in"]),
    ("Permissions and links", ["scmd.set_permissions", "scmd.make_runnable", "scmd.set_owner", "scmd.make_link",
                               "scmd.find_where_link_points"]),
    ("Archives, downloads and other computers", ["scmd.pack_into", "scmd.unpack", "scmd.download_file",
                                                 "scmd.send_files_to", "scmd.get_files_from"]),
    ("Talk to the person at the terminal", ["scmd.ask", "scmd.ask_yes_or_no", "scmd.ask_for_password",
                                            "scmd.ask_to_choose", "scmd.write_in_colour", "scmd.colour_text",
                                            "scmd.show_progress"]),
    ("Keep a record", ["scmd.start_showing_commands", "scmd.stop_showing_commands", "scmd.start_log_in",
                       "scmd.stop_log"]),
    ("Make your own command-line program", ["scmd.CommandLineProgram", "tool.start_from_command_line",
                                            "tool.get_commands", "scmd.make_command_line_program"]),
    ("Learn", ["scmd.show_all_words", "scmd.help", "scmd.show_lesson"]),
]

# Facts on a Result that are plain values, not methods (they have no docstring of their own).
_RESULT_FACTS = {
    "output": "The text the command wrote (its standard output).",
    "errors": "The text the command wrote on its error stream (standard error); many tools write progress here.",
    "seconds": "How many seconds the command took.",
    "cpu_seconds": "The CPU time the program and everything it started used, in seconds (None if unknown).",
    "peak_memory_mb": "The most memory the program used at once, in MB (None if unknown).",
    "attempts": "How many tries the command needed (more than 1 after try_again_if_it_fails).",
}


def _owners():
    import simplycommand as scmd
    from ._running import RunningCommand
    from .command_line_program import CommandLineProgram
    from .program import Pipeline, Program
    from .result import Result

    return {"scmd": scmd, "program": Program, "pipeline": Pipeline, "result": Result,
            "running": RunningCommand, "tool": CommandLineProgram}


def _find(word: str):
    """(full name, object) for a word written as "add_option" or "program.add_option"."""
    owners = _owners()
    names = [n for _, group in GROUPS for n in group]
    if word in names:
        full = word
    else:
        matches = [n for n in names if n.split(".", 1)[1] == word]
        if not matches:
            lines = [f'simplycommand has no word called "{word}".']
            guesses = suggest(word, [n.split(".", 1)[1] for n in names])
            if guesses:
                lines.append("Did you mean " + " or ".join(f'"{g}"' for g in guesses) + "?")
            lines.append("Type scmd.show_all_words() to see every word.")
            raise SimplyCommandError("\n".join(lines))
        full = matches[0]
    owner, name = full.split(".", 1)
    return full, inspect.getattr_static(owners[owner], name, None)


def _doc(full: str, thing) -> str:
    name = full.split(".", 1)[1]
    if full.startswith("result.") and name in _RESULT_FACTS:
        return _RESULT_FACTS[name]
    if isinstance(thing, property):
        thing = thing.fget
    return inspect.getdoc(thing) or ""


def _signature(full: str, thing) -> str:
    if isinstance(thing, property) or (full.startswith("result.") and full.split(".")[1] in _RESULT_FACTS):
        return full
    try:
        sig = inspect.signature(thing.__init__ if inspect.isclass(thing) else thing)
    except (TypeError, ValueError):
        return full
    params = [p for p in sig.parameters.values() if p.name != "self"]
    return f"{full}({', '.join(str(p).replace(' ', '') if p.default is p.empty else str(p) for p in params)})"


def show_all_words() -> None:
    """Print every word of simplycommand, group by group, with what it does."""
    for title, names in GROUPS:
        print(f"\n{title}\n" + "-" * len(title))
        for full in names:
            _, thing = _find(full)
            first = (_doc(full, thing).splitlines() or [""])[0]
            print(f"  {full:<38} {first}" if len(full) < 38 else f"  {full}\n  {'':<38} {first}")
    print('\nOne word in full: scmd.help("add_option"). Lessons: scmd.show_lesson().')


def help(word: str | None = None) -> None:  # noqa: A001  (the word people expect)
    """Explain one word in full: scmd.help("add_option"). With no word, say how to start."""
    if word is None:
        print("simplycommand: simple words for running command-line programs.\n"
              "  scmd.show_all_words()     every word\n"
              '  scmd.help("add_option")   one word in full\n'
              "  scmd.show_lesson(1)       the first lesson")
        return
    full, thing = _find(str(word).split("(")[0].strip())
    print(_signature(full, thing))
    print(textwrap.indent(_doc(full, thing), "    "))


LESSONS = [
    ("Make your own command-line program", """
A function is already a command-line program:

    import simplycommand as scmd

    def hello(name: str, times: int = 1, shout: bool = False):
        \"\"\"Say hello to someone.
        times (-t): how many times to say it
        \"\"\"
        text = f"Hello, {name}!"
        return [text.upper() if shout else text] * times

    if __name__ == "__main__":
        scmd.make_command_line_program(hello)

    $ python hello.py Ann --times 2 --shout
    $ python hello.py --help

A word without a default is typed in order (Ann), a word with a default is an option
(--times 2), a default of False makes a switch (--shout), and the docstring is the help.

A class is a program with several commands, one per method:

    class ToDo(scmd.CommandLineProgram):
        \"\"\"A small to-do list.\"\"\"
        version = "1.0"

        def add(self, task: str, important: bool = False):
            \"\"\"Add a task.\"\"\"
            ...

        def show(self, all: bool = False):
            \"\"\"Show the tasks.\"\"\"
            ...

    if __name__ == "__main__":
        ToDo.start_from_command_line()

    $ python todo.py add "Buy milk" --important
    $ python todo.py show --all

The examples folder goes step by step from here to a complete program.

Try it yourself: make a program with one command that adds two numbers.
"""),
    ("Run another program", """
A program is an object. You make it once, then ask it to run.

    import simplycommand as scmd

    git = scmd.program("git")       # the program; nothing runs yet
    result = git.run("status")      # runs: git status, and waits until it is done
    result.show_output()            # what git wrote
    result.worked                   # True if it ended well (exit code 0)
    result                          # says in one sentence what happened

A whole line works too:  scmd.run_line("git log -n 3").show_output()

Is it installed?  scmd.find_program("samtools")  says where it is, or that it is missing.

Try it yourself: run "python --version" and print the version.
"""),
    ("Options without dashes and quotes", """
Write options as Python options. simplycommand adds the dashes:

    samtools = scmd.program("samtools")
    samtools.run("sort", "reads.bam", o="sorted.bam", threads=4)
    # runs: samtools sort reads.bam -o sorted.bam --threads 4

One letter gets one dash (-o), longer names get two (--threads), underscores become
dashes (min_length= -> --min-length), True is a switch (verbose=True -> --verbose),
False or None leaves the option out, and a list repeats it (I=["a", "b"] -> -I a -I b).

Some tools write options another way. Show simplycommand one example from their help:

    blast = scmd.program("blastn", option_style="-long_name")
    blast.run(query="genes.fa", db="nt", max_target_seqs=5, outfmt=6)
    # runs: blastn -query genes.fa -db nt -max_target_seqs 5 -outfmt 6

Python words such as in or import: end them with _ (in_="x" -> --in x), or write the
option in full: add_option("--in", "x").

Try it yourself: build a command with show_command() and check it before running it.
"""),
    ("Build it up, look, then run", """
Long commands are easier to build one step at a time, like a recipe:

    bwa = scmd.program("bwa", "mem")
    bwa.add_option("t", 8)
    bwa.add_words("genome.fa", "reads_1.fq", "reads_2.fq")
    bwa.save_output_to("aligned.sam")     # like > aligned.sam
    bwa.save_errors_to("bwa.log")         # like 2> bwa.log
    bwa.show_command()                    # look before you run
    bwa.run()

bwa.undo() takes back the last step, bwa.remove_option("t") takes an option out, and
bwa.copy() gives a copy to change for another sample.

Subcommands read like Python:  git.commit(m="Fix")  runs  git commit -m Fix,
and git.cherry_pick("abc123") runs git cherry-pick abc123.

Try it yourself: make one program, then three copies of it for three samples.
"""),
    ("When things go wrong", """
A command that fails stops your script with a plain message: the command, its exit code
and its last lines. The full result is in the error:

    try:
        scmd.program("samtools").run("sort", "missing.bam")
    except scmd.CommandFailedError as error:
        error.result.show_errors()

To carry on instead:  samtools.keep_going_if_it_fails(), then check result.worked.
A program that is not installed raises ProgramNotFoundError, with "Did you mean ...?".
set_time_limit(600) stops a command that runs too long (TimeLimitError).

scmd.start_log_in("commands.log") writes every command, its folder, whether it worked
and how long it took: the exact record for your Methods section.
"""),
    ("Pipes, background and many at once", """
    reads = scmd.program("zcat", "reads.fq.gz") | scmd.program("wc", "-l")
    reads.run().output                     # like: zcat reads.fq.gz | wc -l

    job = scmd.program("bwa", "index", "genome.fa").start_in_background()
    job.is_running()                       # carry on with other work meanwhile
    job.wait_until_done()

    jobs = [scmd.program("fastqc", f) for f in ["a.fq", "b.fq", "c.fq", "d.fq"]]
    results = scmd.run_together(jobs, at_most=2)    # two at a time

show_output_while_running() prints a long tool's progress as it comes.
"""),
    ("Wrap a tool in your own class", """
Give a tool the words of your own work, and hide its options inside:

    class Samtools(scmd.Program):
        program_name = "samtools"

        def sort_file(self, bam, into, threads=4):
            return self.run("sort", bam, o=into, threads=threads)

        def count_reads(self, bam):
            return int(self.run("view", "-c", bam).output)

    samtools = Samtools()
    samtools.sort_file("reads.bam", into="sorted.bam")
    samtools.count_reads("sorted.bam")
"""),
    ("Watch, talk and judge", """
    grep = scmd.program("grep").accept_exit_codes(0, 1)   # 1 only means "nothing found"
    tool.try_again_if_it_fails(times=3, wait=10)          # for downloads and busy servers
    tool.put_errors_into_output()                         # like 2>&1
    tool.do_with_each_line(print, from_errors=True)       # your function on each line, as it comes
    tool.use_text_encoding("latin-1")                     # for tools that do not write UTF-8
    result.get_output_as_bytes()                          # images, archives, other binary output

A program that asks questions:

    py = scmd.program("python", "-i").keep_input_open()
    running = py.start_in_background()
    running.send_text("print(6 * 7)
")
    running.wait_for_text("42")
    running.close_input()

A program that needs your terminal (passwords, editors, progress bars):
    scmd.program("ssh", "server").run_in_this_terminal().run()
"""),
    ("Other places to run", """
The same program, run somewhere else, with one more line:

    fastqc = scmd.program("fastqc", "a.fq")
    fastqc.use_conda_environment("qc")                    # conda run -n qc fastqc a.fq
    fastqc.use_container("biocontainers/fastqc:0.12.1")   # docker run ... fastqc a.fq
    fastqc.use_python_environment("F:/venvs/tools")       # a venv, as if activated
    fastqc.set_computer("me@server.uni.no")               # over ssh on another computer
    fastqc.show_command()                                 # see exactly what will run

They can be joined: a container on another computer, a conda environment in a folder.
use_clean_environment() starts the program with almost no environment variables,
set_priority("low") keeps the computer quick for other work.
"""),
    ("Files and folders", """
What cp, mv, rm, mkdir, find, du, tar and wget do, the same on Windows, macOS and Linux:

    scmd.make_folder("results/plots")
    scmd.copy_file("genes.fa", to="backup/")              # a folder keeps the name
    scmd.move_file("draft.txt", to="final.txt")           # move or rename
    fastqs = scmd.find_files("*.fastq.gz", in_folder="raw")
    scmd.find_size_of("raw")                              # says "raw is 12.4 GB"
    scmd.pack_into("results.zip", "results", "table.csv")
    scmd.unpack("reference.tar.gz", into="reference")
    scmd.download_file("https://example.org/genome.fa.gz", to="reference/")

remove_file and remove_folder delete for good (not to the bin).
"""),
    ("Limits, rights and everything else", """
    tool.set_memory_limit(4000)           # MB; asking for more then fails
    tool.set_cpu_time_limit(3600)         # seconds of computing
    result.cpu_seconds, result.peak_memory_mb    # what it really used (for your Methods)

    tool.run_as_administrator()           # sudo, or "Run as administrator" on Windows
    tool.run_as_user("pipeline")          # Linux and macOS
    pid = tool.start_and_leave_running()  # keeps running after Python ends
    running.send_signal("SIGHUP")         # any signal; "ctrl+break" on Windows

    tool.add_files_matching("raw/**/*_R1.fq.gz")     # what the shell does with wildcards
    tool.save_output_to("out.txt", also_keep=True)   # like tee
    a.send_errors_to(b)                   # pipe the error stream, not the output

And the door to everything else subprocess has:
    tool.use_subprocess_settings(bufsize=0, startupinfo=info)
"""),
    ("Programs that want a person", """
Some programs only ask their questions when they think a person is at a terminal.
A pseudo-terminal makes them think so, and Python answers (like pexpect):

    login = scmd.program("ssh", "me@server", "ls").run_in_pseudo_terminal()
    running = login.start_in_background()
    if running.wait_for_text("password:", time_limit=20):
        running.send_text(scmd.ask_for_password() + "\n")
    running.wait_until_done().show_output()

Your own programs can talk to people too:

    name = scmd.ask("Sample name", default="S1")
    if scmd.ask_yes_or_no("Remove old results?", default=False): ...
    kind = scmd.ask_to_choose("Format?", ["fasta", "fastq"])
    for f in scmd.show_progress(files, label="Checking"): ...
    scmd.write_in_colour("All done", "green")
"""),
]


def show_lesson(number: int | None = None) -> None:
    """Show a short lesson: scmd.show_lesson(1). With no number, list the lessons."""
    if number is None:
        for i, (title, _) in enumerate(LESSONS, 1):
            print(f"  {i}. {title}")
        print("\nType scmd.show_lesson(1) to start.")
        return
    if not 1 <= int(number) <= len(LESSONS):
        raise SimplyCommandError(f"There are lessons 1 to {len(LESSONS)}. Type scmd.show_lesson() to list them.")
    title, text = LESSONS[int(number) - 1]
    heading = f"Lesson {number}: {title}"
    print(heading + "\n" + "=" * len(heading) + text)
    if int(number) < len(LESSONS):
        print(f"Next: scmd.show_lesson({int(number) + 1})")
