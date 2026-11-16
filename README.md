# simplycommand

**Make command-line programs in Python, with simple words.**
Write a function or a class; simplycommand turns it into a command-line program with
commands, options, switches, `--help` and `--version`, friendly error messages, questions,
progress bars and colour. Its other half runs command-line programs from Python as
objects. `argparse` and `subprocess` do the work underneath; there are no other dependencies.

```python
import simplycommand as scmd

def hello(name: str, times: int = 1, shout: bool = False):
    """Say hello to someone.
    times (-t): how many times to say it
    """
    text = f"Hello, {name}!"
    return [text.upper() if shout else text] * times

if __name__ == "__main__":
    scmd.make_command_line_program(hello)
```

```
$ python hello.py Ann --times 2 --shout
HELLO, ANN!
HELLO, ANN!
$ python hello.py --help
```

A class with several methods is a program with several commands; a class inside it is a group
of commands. Six step-by-step examples, from this one to a complete program, are in
[examples/](examples/README.md).

Install (from this folder, until it is on PyPI): `pip install -e .`

## Make your own command-line program

| You write | In the terminal |
|---|---|
| `name: str` (no default) | a word given in order: `Ann` |
| `times: int = 1` | an option: `--times 3` |
| `shout: bool = False` | a switch: `--shout` |
| `colour: bool = True` | `--no-colour` |
| `files: list[Path]` | many words: `a.txt b.txt` |
| `sort: Literal["count", "word"]` | only these choices |
| `top: int \| None = None` | an option you may leave out |
| `"times (-t): ..."` in the docstring | the short letter `-t` and the help text |
| a method of a class | a command: `python todo.py add "Buy milk"` |
| a class inside the class | a group: `python helper.py folder size .` |
| the arguments of `__init__` | options for every command |
| `version = "1.0"` | `--version` |
| `only_one_of = [("json", "table")]` | options that cannot be given together |
| `environment_prefix = "TODO_"` | `TODO_TIMES=3` sets `--times` |
| `defaults_file = "~/.todo.json"` | defaults from a JSON or TOML file |
| `raise scmd.SimplyCommandError("...")` | a plain message, no traceback |

Talk to the person at the terminal:

```python
name = scmd.ask("Your name", default="friend")
if scmd.ask_yes_or_no("Remove every task?", default=False): ...
language = scmd.ask_to_choose("Which language?", ["English", "Norwegian"])
for item in scmd.show_progress(items, label="Working"): ...
scmd.write_in_colour("Done", "green")
```

## Run other command-line programs

A program is an object: you build it up step by step, look at it, run it, and get back a
result that says in one sentence what happened.

```python
samtools = scmd.program("samtools")
result = samtools.run("sort", "reads.bam", o="sorted.bam", threads=4)
# runs: samtools sort reads.bam -o sorted.bam --threads 4
result.worked          # True or False
result                 # The command "samtools sort ..." worked in 2.31 seconds and wrote 0 lines of output.

git = scmd.program("git")
git.status().show_output()          # git status
git.commit(m="Fix the plot")        # git commit -m "Fix the plot"
```

Install (from this folder, until it is on PyPI): `pip install -e .`

## Options without dashes and quotes

Write options as Python options and simplycommand adds the dashes: one letter gets one dash
(`o=` → `-o`), longer names get two (`threads=` → `--threads`), underscores become dashes,
`True` is a switch, `False`/`None` leaves the option out, and a list repeats it.

Tools that write options another way get one example of their style, copied from their help:

```python
blast = scmd.program("blastn", option_style="-long_name")
blast.run(query="genes.fa", db="nt", max_target_seqs=5, outfmt=6)
# runs: blastn -query genes.fa -db nt -max_target_seqs 5 -outfmt 6
```

Styles: `"--long-name"` (default) · `"-long_name"` · `"-long-name"` · `"--long_name"` ·
`"--long-name=value"` · `"/name"` (old Windows tools).

## Build it up, look, then run

```python
bwa = scmd.program("bwa", "mem")
bwa.add_option("t", 8)
bwa.add_words("genome.fa", "reads_1.fq", "reads_2.fq")
bwa.save_output_to("aligned.sam")       # like > aligned.sam (streams to the file)
bwa.save_errors_to("bwa.log")           # like 2> bwa.log
bwa.set_time_limit(3600)
bwa.show_command()                      # look before you run
bwa.run()
bwa.undo()                              # take the last step back
sample_b = bwa.copy()                   # a copy to change for another sample
```

## Pipes, background and many at once

```python
reads = scmd.program("zcat", "reads.fq.gz") | scmd.program("wc", "-l")
reads.run().output

job = scmd.program("bwa", "index", "genome.fa").start_in_background()
job.is_running()
job.wait_until_done()

jobs = [scmd.program("fastqc", f) for f in ["a.fq", "b.fq", "c.fq"]]
results = scmd.run_together(jobs, at_most=2)
```

## Results and errors

```python
result.output, result.errors, result.exit_code, result.seconds
result.get_output_lines()
result.get_output_as_rows()             # split on tabs (or spaces)
result.get_output_as_json()
result.find_lines_with("ERROR")
result.save_output("out.txt")
```

A failed command raises `CommandFailedError` with the command, its exit code and its last
lines (`error.result` has everything). `.keep_going_if_it_fails()` gives a result with
`worked = False` instead. A missing program raises `ProgramNotFoundError` with "Did you mean
...?", and on Windows it says when a Linux command (`ls`, `grep`) has a Windows equivalent.

`scmd.start_log_in("commands.log")` records every command, its folder, whether it worked and
how long it took: the exact record for a Methods section.

## Watch, talk to it and judge it

```python
scmd.program("grep", "ATG", "genes.fa").accept_exit_codes(0, 1)   # 1 only means "nothing found"
tool.try_again_if_it_fails(times=3, wait=10)
tool.put_errors_into_output()                    # 2>&1
tool.do_with_each_line(print, from_errors=True)  # your function on each line, as it comes
tool.use_clean_environment()                     # reproducible runs
tool.set_priority("low")
result.get_output_as_bytes()                     # binary output

running = scmd.program("python", "-i").keep_input_open().start_in_background()
running.send_text("print(6 * 7)
")
running.wait_for_text("42")
running.stop(gently=True)                        # stops everything it started, too

scmd.program("ssh", "server").run_in_this_terminal().run()   # passwords, editors, progress bars
result = await tool.run_async()                  # async code
```

## Other places to run

```python
fastqc = scmd.program("fastqc", "a.fq")
fastqc.use_conda_environment("qc")                    # conda run -n qc fastqc a.fq
fastqc.use_container("biocontainers/fastqc:0.12.1")   # docker/podman/apptainer/singularity
fastqc.use_python_environment("F:/venvs/tools")       # a venv, as if activated
fastqc.set_computer("me@server.uni.no")               # over ssh; they can be joined
```

## Files and folders

What `cp`, `mv`, `rm`, `mkdir`, `find`, `du`, `tar` and `wget` do, the same on every computer:

```python
scmd.make_folder("results/plots")
scmd.copy_file("genes.fa", to="backup/")
fastqs = scmd.find_files("*.fastq.gz", in_folder="raw")
scmd.find_size_of("raw")                              # says "raw is 12.4 GB"
scmd.pack_into("results.zip", "results", "table.csv")
scmd.unpack("reference.tar.gz", into="reference")
scmd.download_file("https://example.org/genome.fa.gz", to="reference/")
```

## Wrap a tool in your own class

```python
class Samtools(scmd.Program):
    program_name = "samtools"

    def sort_file(self, bam, into, threads=4):
        return self.run("sort", bam, o=into, threads=threads)

    def count_reads(self, bam):
        return int(self.run("view", "-c", bam).output)
```

## Learn it

```python
scmd.show_all_words()        # every word, group by group
scmd.help("add_option")      # one word in full
scmd.show_lesson(1)          # twelve short lessons
```

## The rules for words

simplycommand follows the rules of [simplydata](https://github.com/bioforkgithub/simplydata):
a line reads like an instruction said to the program (object, verb, details); words follow a
few patterns you can guess from one sibling (`add_`, `remove_`, `set_`, `use_`, `save_..._to`,
`show_`/`hide_`, `get_`, `find_`, `make_`); results say what happened in a sentence; errors
say what went wrong and guess what was meant. See [PLAN.md](PLAN.md).
