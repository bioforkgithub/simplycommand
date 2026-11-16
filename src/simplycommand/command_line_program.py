"""Make your own command-line program from a Python class (argparse does the work underneath).

    import simplycommand as scmd
    from typing import Literal

    class Sequences(scmd.CommandLineProgram):
        \"\"\"Small tools for FASTA files.\"\"\"
        version = "1.0"
        only_one_of = [("json", "tsv")]          # options that cannot be given together
        environment_prefix = "SEQS_"             # SEQS_MIN_LENGTH=50 sets --min-length
        defaults_file = "~/.seqs.json"           # defaults from a JSON (or TOML) file

        def __init__(self, verbose: bool = False):
            \"\"\"verbose (-v): say more about what is done\"\"\"
            self.verbose = verbose

        def count(self, fasta: str, min_length: int = 0, json: bool = False, tsv: bool = False):
            \"\"\"Count the sequences in a FASTA file.
            fasta: the file to read
            min_length (-m): only count sequences at least this long
            \"\"\"
            ...

        class database(scmd.CommandLineProgram):    # a group of commands: seqs database add ...
            \"\"\"Work with the sequence database.\"\"\"
            def add(self, fasta: str): ...

    if __name__ == "__main__":
        Sequences.start_from_command_line()

Then:  python seqs.py count genes.fa -m 100        python seqs.py --verbose database add new.fa
       python seqs.py --help                       python seqs.py --version

Each method is a command, each argument without a default is given in order, each argument with a
default is an option (--min-length), an argument that defaults to False is a switch, a default of True
gives --no-name, and Literal[...] lists the allowed choices. The arguments of __init__ are options for
every command (given before the command). A class inside the class is a group of commands.
"name (-m): text" in a docstring gives the option a short letter and its help. If the argcomplete
package is installed, the program gets tab completion (see its documentation to switch it on).
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
import typing
from pathlib import Path

from ._errors import SimplyCommandError


class _ClassOrObject:
    """Lets start_from_command_line work on the class (Sequences.start_from_command_line(), which also reads
    the options of __init__) and on an object you made yourself (Sequences().start_from_command_line())."""

    def __init__(self, function):
        self.function = function
        self.__doc__ = function.__doc__

    def __get__(self, obj, cls):
        return lambda words=None: self.function(cls, obj, words)


def _start_from_command_line(cls, obj, words=None):
    """Read the words typed in the terminal (or the list `words`), run the matching method and print what
    it gives back. Gives back what the method gave back.

    Called on the class (Sequences.start_from_command_line()), the arguments of __init__ become options
    for every command; called on an object, that object is used as it is."""
    return _start(obj if obj is not None else cls, words)


class CommandLineProgram:
    """Inherit from this; every public method of your class becomes a command of the program."""

    version: str | None = None
    only_one_of: list = []
    environment_prefix: str | None = None
    defaults_file: str | None = None

    start_from_command_line = _ClassOrObject(_start_from_command_line)

    @classmethod
    def get_commands(cls) -> list[str]:
        """The names of the commands, as they are typed in the terminal."""
        return [_dashed(name) for name in _commands_of(cls)]


def make_command_line_program(thing, words: list[str] | None = None):
    """Turn a function, a class or an object into a command-line program and run it.

        def resize(image: str, width: int = 800, keep_ratio: bool = True): ...
        if __name__ == "__main__":
            scmd.make_command_line_program(resize)

    A function is a program with one command; every public method of a class or object is a command,
    and the arguments of a class's __init__ are options for every command.
    """
    return _start(thing, words)


# ---------------------------------------------------------------- inside
_BASE_WORDS = {"start_from_command_line", "get_commands", "version", "only_one_of", "environment_prefix",
               "defaults_file"}


def _is_group(value) -> bool:
    return inspect.isclass(value) and issubclass(value, CommandLineProgram)


def _commands_of(cls) -> dict:
    """{name: function or group class} for the public methods and inner command classes of the class."""
    commands = {}
    for name in dir(cls):
        if name.startswith("_") or name in _BASE_WORDS:
            continue
        value = inspect.getattr_static(cls, name, None)
        if isinstance(value, (staticmethod, classmethod)):
            commands[name] = getattr(cls, name)
        elif inspect.isfunction(value) or _is_group(value):
            commands[name] = value
    if not commands:
        raise SimplyCommandError(f"{cls.__name__} has no commands yet. "
                                 "Add a method, for example: def count(self, file: str): ...")
    return commands


def _describe(thing) -> str:
    doc = inspect.getdoc(thing) or ""
    for base in (CommandLineProgram, object):
        if doc == (inspect.getdoc(base) or None):
            return ""
    return doc


def _dashed(name: str) -> str:
    return name.replace("_", "-")


class _Context:
    """What one program brings to every level: defaults from a file and from environment variables."""

    def __init__(self, cls):
        self.only_one_of = [tuple(group) for group in getattr(cls, "only_one_of", []) or []]
        self.prefix = getattr(cls, "environment_prefix", None)
        self.file_defaults = _read_defaults(getattr(cls, "defaults_file", None))

    def default_for(self, command_path: tuple, name: str, default, kind):
        value = default
        place = self.file_defaults
        found = _lookup(place, name)
        for step in command_path:  # a section per command overrides the general one
            place = place.get(step) or place.get(_dashed(step)) or {} if isinstance(place, dict) else {}
            inner = _lookup(place, name)
            if inner is not _MISSING:
                found = inner
        if found is not _MISSING:
            value = found
        if self.prefix:
            text = os.environ.get(self.prefix + name.upper())
            if text is not None:
                value = _from_text(text, kind, name)
        return value


_MISSING = object()


def _lookup(place, name):
    if not isinstance(place, dict):
        return _MISSING
    for key in (name, _dashed(name)):
        if key in place and not isinstance(place[key], dict):
            return place[key]
    return _MISSING


def _from_text(text: str, kind, name: str):
    if kind is bool:
        low = text.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off", ""):
            return False
        raise SimplyCommandError(f'The environment variable for {name} should be yes or no, not "{text}".')
    try:
        return kind(text)
    except ValueError:
        raise SimplyCommandError(f'The environment variable for {name} should be a {kind.__name__}, not "{text}".') from None


def _read_defaults(file_name) -> dict:
    if not file_name:
        return {}
    path = Path(os.path.expanduser(os.fspath(file_name)))
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        if path.suffix.lower() == ".toml":
            try:
                import tomllib
            except ImportError:
                raise SimplyCommandError("Reading a .toml defaults file needs Python 3.11 or newer; "
                                         "use a .json file instead.") from None
            return tomllib.loads(text)
        return json.loads(text)
    except (ValueError, TypeError) as error:
        raise SimplyCommandError(f'The defaults file "{path}" could not be read: {error}') from None


def _start(thing, words):
    if inspect.isfunction(thing) or inspect.ismethod(thing) or inspect.isbuiltin(thing):
        cls, target, commands = None, None, {thing.__name__: thing}
        description, context = _describe(thing), _Context(object)
    else:
        cls = thing if inspect.isclass(thing) else type(thing)
        target, commands = thing, _commands_of(cls)
        description, context = _describe(cls), _Context(cls)

    parser = argparse.ArgumentParser(description=_first_paragraph(description),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    version = getattr(cls, "version", None) if cls else None
    if version:
        parser.add_argument("--version", action="version", version=str(version))
    single = (cls is None or (len(commands) == 1 and not _init_takes_options(cls)
                              and not any(_is_group(c) for c in commands.values())))
    _fill(parser, cls if inspect.isclass(target) else None, commands, (), context, single)
    try:
        import argcomplete  # optional: tab completion

        argcomplete.autocomplete(parser)
    except ImportError:
        pass
    parsed = vars(parser.parse_args(words))

    level, path, obj = 0, (), target
    while True:
        if inspect.isclass(obj):
            names = parsed.pop(f"_init_names{level}", [])
            values = {name: parsed.pop(f"_init{level}_{name}") for name in names}
            try:
                obj = obj(**values)
            except SimplyCommandError as error:
                _fail(error)
        chosen = parsed.pop(f"_chosen{level}", None) if not single else next(iter(commands.values()))
        parsed.pop(f"_command{level}", None)
        if _is_group(chosen):
            obj, level = chosen, level + 1
            continue
        break

    args, kwargs = _call_values(chosen, parsed)
    if obj is not None and inspect.isfunction(chosen) and _takes_self(chosen):
        chosen = chosen.__get__(obj)
    try:
        answer = chosen(*args, **kwargs)
    except SimplyCommandError as error:  # a plain-English problem: no traceback for the user
        _fail(error)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        raise SystemExit(130) from None
    _print_answer(answer)
    return answer


def _init_takes_options(cls) -> bool:
    return cls is not None and cls.__init__ is not object.__init__ and \
        any(p not in ("self",) for p in inspect.signature(cls.__init__).parameters)


def _fill(parser, cls, commands: dict, path: tuple, context: _Context, single: bool) -> None:
    """Add the options of the class's __init__ and its commands (or groups) to the parser."""
    level = len(path)
    if cls is not None and _init_takes_options(cls):
        names = _add_arguments(parser, cls.__init__, context, path, prefix=f"_init{level}_")
        parser.set_defaults(**{f"_init_names{level}": names})
    if single:
        (name, func), = commands.items()
        _add_arguments(parser, func, context, path)
        return
    subs = parser.add_subparsers(dest=f"_command{level}", metavar="command", title="commands")
    subs.required = True
    for name, item in commands.items():
        doc = _describe(item)
        aliases = [name] if _dashed(name) != name else []
        sub = subs.add_parser(_dashed(name), aliases=aliases, help=_first_line(doc), description=_first_paragraph(doc),
                              formatter_class=argparse.RawDescriptionHelpFormatter)
        sub.set_defaults(**{f"_chosen{level}": item})
        if _is_group(item):
            _fill(sub, item, _commands_of(item), (*path, name), context, False)
        else:
            _add_arguments(sub, item, context, (*path, name))


def _takes_self(func) -> bool:
    params = list(inspect.signature(func).parameters)
    return bool(params) and params[0] == "self"


def _fail(error) -> None:
    print(f"Error: {error}", file=sys.stderr)
    raise SystemExit(1) from None


def _call_values(func, parsed: dict):
    args, kwargs = [], {}
    for param in inspect.signature(func).parameters.values():
        if param.name not in parsed:
            continue
        value = parsed[param.name]
        if param.kind is param.VAR_POSITIONAL:
            args += value or []
        elif param.default is param.empty:
            args.append(value)
        else:
            kwargs[param.name] = value
    return args, kwargs


def _print_answer(answer) -> None:
    if answer is None:
        return
    from .result import Result

    if isinstance(answer, Result):
        print(answer.output, end="")
    elif isinstance(answer, dict):
        for key, value in answer.items():
            print(f"{key}: {value}")
    elif isinstance(answer, (list, tuple, set)):
        for item in answer:
            print(item)
    else:
        print(answer)


def _add_arguments(parser: argparse.ArgumentParser, func, context: _Context, path: tuple,
                   prefix: str = "") -> list[str]:
    """Add the function's arguments to the parser; gives their names."""
    helps, shorts = _argument_help(inspect.getdoc(func) or "")
    try:
        hints = typing.get_type_hints(func)
    except Exception:  # hints that cannot be read are simply not used
        hints = {}
    params = [p for p in inspect.signature(func).parameters.values()
              if p.name not in ("self", "cls") and p.kind is not p.VAR_KEYWORD]
    names = {p.name for p in params}
    groups = {}
    for together in context.only_one_of:
        if sum(1 for n in together if n in names) >= 2:
            group = parser.add_mutually_exclusive_group()
            for n in together:
                groups[n] = group
    added = []
    for param in params:
        added.append(param.name)
        target = groups.get(param.name, parser)
        kind, many, choices = _kind(hints.get(param.name), param.default)
        text = helps.get(param.name, "")
        dest = prefix + param.name
        flags = [f"--{_dashed(param.name)}"]
        if param.name in shorts:
            flags.insert(0, f"-{shorts[param.name]}")
        default = param.default
        if default is not param.empty:
            default = context.default_for(path, param.name, default, kind)
        if param.kind is param.VAR_POSITIONAL:
            parser.add_argument(dest, nargs="*", type=kind, help=text, metavar=param.name)
        elif param.default is param.empty and not prefix:
            parser.add_argument(dest, nargs="+" if many else None, type=kind, help=text, choices=choices,
                                metavar=param.name if not choices else None)
        elif param.default is param.empty:  # __init__ argument without a default: a required option
            target.add_argument(*flags, dest=dest, type=kind, required=True, help=text, choices=choices,
                                nargs="+" if many else None)
        elif kind is bool:
            if param.default is True:
                no = [f"--no-{_dashed(param.name)}"] + ([f"-{shorts[param.name]}"] if param.name in shorts else [])
                target.add_argument(*no, dest=dest, action="store_false", default=default,
                                    help=text or f"turn off {_dashed(param.name)}")
            else:
                target.add_argument(*flags, dest=dest, action="store_true", default=default, help=text)
        else:
            shown = f" (default: {default})" if default not in (None, [], ()) else ""
            target.add_argument(*flags, dest=dest, type=kind, default=default, choices=choices,
                                nargs="*" if many else None, help=(text + shown).strip(),
                                metavar=None if choices else param.name.upper())
    return added


def _kind(hint, default):
    """(type to turn each word into, whether it takes many words, allowed choices or None)."""
    if hint is None:
        if default is inspect.Parameter.empty or default is None:
            return str, False, None
        if isinstance(default, (list, tuple)):
            return (type(default[0]) if default else str), True, None
        return type(default), False, None
    origin = typing.get_origin(hint)
    if origin is typing.Literal:
        choices = list(typing.get_args(hint))
        return type(choices[0]), False, choices
    if origin in (list, tuple, set):
        inner = [a for a in typing.get_args(hint) if a is not Ellipsis]
        kind, _, choices = _kind(inner[0] if inner else None, inspect.Parameter.empty)
        return kind, True, choices
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":  # Optional[int], int | None
        inner = [a for a in typing.get_args(hint) if a is not type(None)]
        return _kind(inner[0] if inner else None, default)
    if hint in (str, int, float, bool, Path):
        return hint, False, None
    return str, False, None


def _first_line(doc: str) -> str:
    return doc.strip().splitlines()[0] if doc.strip() else ""


def _first_paragraph(doc: str) -> str:
    """The description without the lines that explain single arguments."""
    lines = []
    for line in doc.strip().splitlines():
        if _ARG_LINE.match(line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


_ARG_LINE = re.compile(r"^\s*(\w+)\s*(?:\(\s*-(\w)\s*\))?\s*:\s+(.+)$")


def _argument_help(doc: str):
    """Lines such as "min_length (-m): only long ones" in a docstring: (help per argument, short letter per argument)."""
    helps, shorts = {}, {}
    for line in doc.splitlines():
        found = _ARG_LINE.match(line)
        if found:
            helps[found.group(1)] = found.group(3).strip()
            if found.group(2):
                shorts[found.group(1)] = found.group(2)
    return helps, shorts
