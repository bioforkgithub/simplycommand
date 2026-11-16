# Examples: how to make a command-line program

Six small programs, from the smallest to a complete one. Each file starts with the lines to type
in the terminal and explains what each part of the code does. Read them in order.

| File | You learn |
|---|---|
| `01_hello.py` | The smallest program: one function. Words in order, options, switches, short letters, `--help` from the docstring. |
| `02_kinds_of_options.py` | Every kind of option: many files, numbers, choices, options you may leave out, `--no-...`, file names, and friendly errors. |
| `03_several_commands.py` | Several commands from one class (a to-do list), options shared by every command, `--version`, asking before doing something. |
| `04_groups_and_settings.py` | Groups of commands (`folder ...`, `computer ...`), options that exclude each other, settings from environment variables and a file. |
| `05_talking_to_people.py` | Questions, choices, a progress bar and colour, while still working without a person (every question is also an option). |
| `06_running_other_programs.py` | A program that runs other programs: versions, timing, pipes, many at once, and a log of what was run. |

Run any of them with `--help` first:

```
python 01_hello.py --help
```

Examples from real research (sequence files, alignment tools, whole pipelines) are worked
through as projects in the manual.
