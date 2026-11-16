"""Step 3: a program with several commands, made from a class: a small to-do list.

Try in the terminal:
    python 03_several_commands.py add "Buy milk"
    python 03_several_commands.py add "Write the report" --important
    python 03_several_commands.py show
    python 03_several_commands.py done 1
    python 03_several_commands.py show --all
    python 03_several_commands.py --list-file work.json add "Send the data"
    python 03_several_commands.py clear --yes
    python 03_several_commands.py --version
    python 03_several_commands.py --help          python 03_several_commands.py add --help

How it is built:
    each method of the class        is a command (add, show, done, clear)
    the arguments of __init__       are options for every command, given before the command (--list-file)
    version = "1.0"                 gives --version
    Class.start_from_command_line() starts it (from the class, so that __init__ gets its options)
"""

import json
from pathlib import Path

import simplycommand as scmd


class ToDo(scmd.CommandLineProgram):
    """A small to-do list kept in a JSON file."""

    version = "1.0"

    def __init__(self, list_file: Path = Path("todo.json")):
        """list_file (-f): the file that keeps the list"""
        self.list_file = list_file

    def add(self, task: str, important: bool = False):
        """Add a task to the list.
        task: what to do (in quotes if it has spaces)
        important (-i): mark it as important
        """
        tasks = self._read()
        tasks.append({"task": task, "important": important, "done": False})
        self._write(tasks)
        return f"Added task {len(tasks)}: {task}"

    def show(self, all: bool = False):
        """Show the tasks that are not done yet.
        all (-a): show the done tasks too
        """
        lines = []
        for number, item in enumerate(self._read(), 1):
            if item["done"] and not all:
                continue
            mark = "x" if item["done"] else " "
            star = " (!)" if item["important"] else ""
            lines.append(f"[{mark}] {number}. {item['task']}{star}")
        return lines or ["Nothing to do."]

    def done(self, number: int):
        """Mark a task as done.
        number: the task's number, as show prints it
        """
        tasks = self._read()
        if not 1 <= number <= len(tasks):
            raise scmd.SimplyCommandError(f"There is no task {number}; the list has {len(tasks)}.")
        tasks[number - 1]["done"] = True
        self._write(tasks)
        return f"Done: {tasks[number - 1]['task']}"

    def clear(self, yes: bool = False):
        """Remove every task from the list.
        yes (-y): do not ask first
        """
        if not yes and not scmd.ask_yes_or_no("Remove every task?", default=False):
            return "Nothing was removed."
        self._write([])
        return "The list is empty."

    # Methods whose names start with _ are not commands: they are helpers inside the class.
    def _read(self) -> list:
        if not self.list_file.exists():
            return []
        return json.loads(self.list_file.read_text(encoding="utf-8"))

    def _write(self, tasks: list) -> None:
        self.list_file.write_text(json.dumps(tasks, indent=2), encoding="utf-8")


if __name__ == "__main__":
    ToDo.start_from_command_line()
