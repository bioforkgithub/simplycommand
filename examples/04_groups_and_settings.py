"""Step 4: a bigger program: groups of commands, options that exclude each other, and settings
read from environment variables and from a file.

Try in the terminal:
    python 04_groups_and_settings.py folder size .
    python 04_groups_and_settings.py folder biggest . --how-many 3
    python 04_groups_and_settings.py folder find "*.py" --in-folder .
    python 04_groups_and_settings.py computer info
    python 04_groups_and_settings.py computer info --as-json
    python 04_groups_and_settings.py computer has python git
    python 04_groups_and_settings.py --help        python 04_groups_and_settings.py folder --help

Settings without typing them each time:
    environment variable   HELPER_HOW_MANY=10      (environment_prefix = "HELPER_")
    a file ~/.helper.json   {"how_many": 10, "folder": {"biggest": {"how_many": 3}}}
    The order is: the default in the code, then the file, then the environment variable,
    and an option typed in the terminal wins over all of them.

How it is built:
    a class inside the class          is a group of commands (folder ..., computer ...)
    only_one_of = [(...)]             options that cannot be given together
"""

import os
import platform
import sys

import simplycommand as scmd


class Helper(scmd.CommandLineProgram):
    """Small everyday helpers for folders and this computer."""

    version = "1.0"
    environment_prefix = "HELPER_"
    defaults_file = "~/.helper.json"
    only_one_of = [("as_json", "as_table")]

    class folder(scmd.CommandLineProgram):
        """Look at folders and the files in them."""

        def size(self, path: str):
            """Say how big a folder is, with everything in it.
            path: the folder (. is the folder you are in)
            """
            scmd.find_size_of(path)  # prints its answer in a sentence

        def biggest(self, path: str, how_many: int = 5):
            """List the biggest files in a folder.
            path: the folder (. is the folder you are in)
            how_many (-n): how many files to list
            """
            sizes = [(os.path.getsize(f), f) for f in scmd.find_files("*", in_folder=path)]
            sizes.sort(reverse=True)
            return [f"{size:>12,} bytes  {name}" for size, name in sizes[:how_many]]

        def find(self, pattern: str, in_folder: str = "."):
            """List the files whose names match a pattern, such as "*.csv"."""
            return scmd.find_files(pattern, in_folder=in_folder) or ["No files match."]

    class computer(scmd.CommandLineProgram):
        """Facts about this computer."""

        def info(self, as_json: bool = False, as_table: bool = False):
            """Show the system, the Python version and the free disk space."""
            import json
            import shutil

            facts = {"system": platform.platform(), "python": sys.version.split()[0],
                     "free disk space (GB)": round(shutil.disk_usage(".").free / 1e9, 1)}
            if as_json:
                return json.dumps(facts, indent=2)
            if as_table:
                return [f"{key:<22} {value}" for key, value in facts.items()]
            return facts  # a dict is printed as "key: value" lines

        def has(self, *programs: str):
            """Say which of these programs are installed."""
            return [f"{name:<12} {'yes' if scmd.program(name).is_installed() else 'no'}" for name in programs]


if __name__ == "__main__":
    Helper.start_from_command_line()
