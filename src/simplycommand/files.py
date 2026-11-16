"""Files and folders in plain words: what cp, mv, rm, mkdir, find, du, tar, zip, cd and wget do,
done by shutil, pathlib, zipfile, tarfile and urllib underneath, the same on every computer.

    scmd.make_folder("results/plots")
    scmd.copy_file("genes.fa", to="backup/")
    fastqs = scmd.find_files("*.fastq.gz", in_folder="raw")
    scmd.pack_into("results.zip", "results")
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from ._errors import SimplyCommandError, choice_error, suggest

_ARCHIVES = [".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"]


def _not_found(path, kind: str = "file or folder") -> SimplyCommandError:
    path = Path(path)
    lines = [f'The {kind} "{path}" does not exist.']
    parent = path.parent if str(path.parent) else Path(".")
    try:
        guesses = suggest(path.name, os.listdir(parent), n=2)
    except OSError:
        guesses = []
    if guesses:
        lines.append("Did you mean " + " or ".join(f'"{parent / g}"' for g in guesses) + "?")
    lines.append(f"The current folder is {os.getcwd()}")
    return SimplyCommandError("\n".join(lines))


def _target(source: Path, to) -> Path:
    """`to` as a full target: a folder (existing, or written with a slash at the end) gets the source's name."""
    text = os.fspath(to)
    target = Path(text)
    if target.is_dir() or text.endswith(("/", "\\")):
        target.mkdir(parents=True, exist_ok=True)
        return target / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def make_folder(folder) -> str:
    """Make a folder, with the folders above it if they are missing (like mkdir -p). Fine if it exists."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    return os.fspath(folder)


def copy_file(file, to) -> str:
    """Copy a file. to= a new file name, or a folder ("backup/") to keep the name. Gives the new path."""
    source = Path(file)
    if source.is_dir():
        raise SimplyCommandError(f'"{source}" is a folder. Use scmd.copy_folder to copy a folder.')
    if not source.is_file():
        raise _not_found(source, "file")
    return os.fspath(shutil.copy2(source, _target(source, to)))


def copy_folder(folder, to) -> str:
    """Copy a folder with everything in it (like cp -r). to= the new folder. Gives the new path."""
    source = Path(folder)
    if not source.is_dir():
        raise _not_found(source, "folder")
    target = Path(to)
    if target.exists():
        raise SimplyCommandError(f'"{target}" already exists. Give a new folder name, or remove it first.')
    return os.fspath(shutil.copytree(source, target))


def move_file(file, to) -> str:
    """Move or rename a file (like mv). to= a new name, or a folder ("done/") to keep the name."""
    source = Path(file)
    if not source.is_file():
        raise _not_found(source, "file")
    return os.fspath(shutil.move(os.fspath(source), os.fspath(_target(source, to))))


def move_folder(folder, to) -> str:
    """Move or rename a folder with everything in it (like mv)."""
    source = Path(folder)
    if not source.is_dir():
        raise _not_found(source, "folder")
    return os.fspath(shutil.move(os.fspath(source), os.fspath(to)))


def remove_file(file, if_it_exists: bool = False) -> None:
    """Delete a file for good (like rm; it does not go to the bin). if_it_exists=True: no error if it is missing."""
    path = Path(file)
    if path.is_dir():
        raise SimplyCommandError(f'"{path}" is a folder. Use scmd.remove_folder to remove a folder.')
    if not path.exists():
        if if_it_exists:
            return
        raise _not_found(path, "file")
    path.unlink()


def remove_folder(folder, if_it_exists: bool = False) -> None:
    """Delete a folder and everything in it, for good (like rm -r). if_it_exists=True: no error if it is missing."""
    path = Path(folder)
    if not path.exists():
        if if_it_exists:
            return
        raise _not_found(path, "folder")
    if not path.is_dir():
        raise SimplyCommandError(f'"{path}" is a file. Use scmd.remove_file to remove a file.')
    if path.resolve() in (Path.home().resolve(), Path(path.resolve().anchor)):
        raise SimplyCommandError(f'simplycommand will not remove "{path}": it is your home folder or a whole drive.')
    shutil.rmtree(path)


def find_files(pattern: str = "*", in_folder=".", in_subfolders: bool = True, with_folders: bool = False) -> list[str]:
    """The files whose names match a pattern, sorted (like find or dir /s): find_files("*.fastq.gz", in_folder="raw").

    * is any text and ? one letter. A pattern with a folder in it matches the whole path inside in_folder:
    find_files("*/R1_*.fq") or find_files("run*/**/*.bam") (** is any number of folders).
    in_subfolders=False looks only in the folder itself; with_folders=True gives matching folders too.
    """
    base = Path(in_folder)
    if not base.is_dir():
        raise _not_found(base, "folder")
    if "/" in pattern or "\\" in pattern:
        found = base.glob(pattern.replace("\\", "/"))
        return sorted(os.fspath(p) for p in found if with_folders or p.is_file())
    found = base.rglob("*") if in_subfolders else base.glob("*")
    return sorted(os.fspath(p) for p in found
                  if fnmatch.fnmatch(p.name, pattern) and (with_folders or p.is_file()))


def find_size_of(path) -> int:
    """Say how big a file or folder is (a folder: everything in it, like du -sh), and give the size in bytes."""
    path = Path(path)
    if not path.exists():
        raise _not_found(path)
    if path.is_file():
        size = path.stat().st_size
    else:
        size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    print(f'"{path}" is {readable_size(size)}.')
    return size


def readable_size(size: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size} bytes"  # pragma: no cover


def get_current_folder() -> str:
    """The folder Python is working in now (like pwd)."""
    return os.getcwd()


def set_current_folder(folder) -> str:
    """Make this the folder Python works in (like cd). Gives the full path."""
    path = Path(folder)
    if not path.is_dir():
        raise _not_found(path, "folder")
    os.chdir(path)
    return os.getcwd()


def _kind_of_archive(name: str) -> str:
    low = name.lower()
    for ending in sorted(_ARCHIVES, key=len, reverse=True):
        if low.endswith(ending):
            return ending
    raise choice_error("the archive name", "ending", os.path.splitext(name)[1] or name, _ARCHIVES)


def pack_into(archive, *things) -> str:
    """Pack files and folders into one archive (like zip or tar): pack_into("results.zip", "plots", "table.csv").
    The kind comes from the name: .zip, .tar, .tar.gz, .tgz, .tar.bz2 or .tar.xz."""
    archive = os.fspath(archive)
    kind = _kind_of_archive(archive)
    if not things:
        raise SimplyCommandError(f'Say what to pack: pack_into("{archive}", "folder_or_file", ...).')
    paths = [Path(t) for t in things]
    for path in paths:
        if not path.exists():
            raise _not_found(path)
    if os.path.dirname(archive):
        os.makedirs(os.path.dirname(archive), exist_ok=True)
    if kind == ".zip":
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                members = [path] + (sorted(path.rglob("*")) if path.is_dir() else [])
                for member in members:
                    zf.write(member, os.path.relpath(member, path.parent))
    else:
        mode = {".tar": "w", ".tar.gz": "w:gz", ".tgz": "w:gz", ".tar.bz2": "w:bz2", ".tar.xz": "w:xz"}[kind]
        with tarfile.open(archive, mode) as tf:
            for path in paths:
                tf.add(path, arcname=path.name)
    return archive


def unpack(archive, into=".") -> list[str]:
    """Unpack a .zip or .tar(.gz/.bz2/.xz) archive into a folder (like unzip or tar -x). Gives the paths unpacked.

    Files that would land outside the folder (a known trick in bad archives) are refused.
    """
    archive = os.fspath(archive)
    if not os.path.isfile(archive):
        raise _not_found(archive, "archive")
    kind = _kind_of_archive(archive)
    target = Path(into).resolve()
    target.mkdir(parents=True, exist_ok=True)
    if kind == ".zip":
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            _check_inside(target, names)
            zf.extractall(target)
    else:
        with tarfile.open(archive) as tf:
            names = tf.getnames()
            _check_inside(target, names)
            try:
                tf.extractall(target, filter="data")
            except TypeError:  # Python before 3.10.12 has no filter=
                tf.extractall(target)
    return [os.fspath(target / n) for n in names]


def _check_inside(target: Path, names) -> None:
    for name in names:
        if not (target / name).resolve().is_relative_to(target):
            raise SimplyCommandError(f'The archive wants to write "{name}" outside the folder "{target}". '
                                     "It was not unpacked.")


def download_file(url: str, to=None) -> str:
    """Download a file from the internet (like wget or curl -O). to= a file name or folder; without it the
    file keeps its own name in the current folder. Gives the path of the file."""
    name = os.path.basename(urllib.parse.urlparse(url).path) or "download"
    target = _target(Path(name), to) if to is not None else Path(name)
    request = urllib.request.Request(url, headers={"User-Agent": "simplycommand"})
    try:
        with urllib.request.urlopen(request) as response, open(target, "wb") as handle:
            shutil.copyfileobj(response, handle)
    except OSError as error:
        if target.exists():
            target.unlink()
        raise SimplyCommandError(f"The download from {url} did not work: {error}") from None
    return os.fspath(target)


# ---------------------------------------------------------------- permissions, owners and links
def set_permissions(path, permissions) -> None:
    """Set who may read, write and run a file (like chmod): set_permissions("run.sh", "rwxr-xr-x") or 0o755.
    On Windows only "may be changed or not" exists: a permission without any w makes the file read-only."""
    path = Path(path)
    if not path.exists():
        raise _not_found(path)
    if isinstance(permissions, str):
        text = permissions.strip()
        good = len(text) == 9 and all(text[i] in ("-", "rwx"[i % 3]) for i in range(9))
        if not good:
            raise SimplyCommandError(f'"{permissions}" is not a permission like "rwxr-xr-x" (or a number like 0o755).')
        mode = sum(1 << (8 - i) for i, c in enumerate(text) if c != "-")
    else:
        mode = int(permissions)
    os.chmod(path, mode)


def make_runnable(file) -> None:
    """Let a file be run as a program (like chmod +x). On Windows, files run by their ending (.exe, .bat)."""
    import stat

    path = Path(file)
    if not path.is_file():
        raise _not_found(path, "file")
    os.chmod(path, path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def set_owner(path, user=None, group=None) -> None:
    """Give a file or folder to another user and/or group (like chown). Linux and macOS only."""
    if os.name == "nt":
        raise SimplyCommandError("set_owner works only on Linux and macOS; on Windows use the file's Security settings.")
    path = Path(path)
    if not path.exists():
        raise _not_found(path)
    shutil.chown(path, user=user, group=group)


def make_link(pointing_to, at) -> str:
    """Make a link (symbolic link) at `at` that points to a file or folder (like ln -s). Gives the link's path.
    On Windows this needs Developer Mode or administrator rights."""
    target = Path(pointing_to)
    link = Path(at)
    if link.exists() or link.is_symlink():
        raise SimplyCommandError(f'"{link}" already exists. Remove it first, or choose another name.')
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as error:
        if os.name == "nt":
            raise SimplyCommandError("Windows did not allow the link. Turn on Developer Mode "
                                     "(Settings > System > For developers) or run Python as administrator.") from None
        raise SimplyCommandError(f"The link could not be made: {error}") from None
    return os.fspath(link)


def find_where_link_points(link) -> str:
    """Say where a link points to, and give that path."""
    path = Path(link)
    if not path.is_symlink():
        raise SimplyCommandError(f'"{path}" is not a link.')
    target = os.readlink(path)
    print(f'"{path}" points to "{target}".')
    return target


# ---------------------------------------------------------------- facts about files and disks
def get_file_dates(path) -> dict:
    """When a file or folder was changed, last opened and made, as datetime values in a dict
    ("made" is the change time of its details on Linux, where the making time is not kept)."""
    import datetime

    path = Path(path)
    if not path.exists():
        raise _not_found(path)
    info = path.stat()
    made = getattr(info, "st_birthtime", info.st_ctime)
    when = datetime.datetime.fromtimestamp
    return {"changed": when(info.st_mtime), "opened": when(info.st_atime), "made": when(made)}


def find_free_space(folder=".") -> int:
    """Say how much space is free on the disk that holds this folder, and give it in bytes (like df -h)."""
    folder = Path(folder)
    if not folder.exists():
        raise _not_found(folder, "folder")
    usage = shutil.disk_usage(folder)
    print(f'The disk with "{folder.resolve()}" has {readable_size(usage.free)} free of {readable_size(usage.total)}.')
    return usage.free


def make_temporary_folder(start_of_name: str = "scmd_") -> str:
    """Make a new empty folder in the computer's temporary folder, and give its path. Remove it with
    scmd.remove_folder when you are done."""
    import tempfile

    return tempfile.mkdtemp(prefix=start_of_name)


def make_temporary_file(ending: str = "", start_of_name: str = "scmd_") -> str:
    """Make a new empty file in the computer's temporary folder (ending=".fa" for a FASTA file), and give its path."""
    import tempfile

    handle, path = tempfile.mkstemp(suffix=ending, prefix=start_of_name)
    os.close(handle)
    return path


def wait_for_change_in(folder, time_limit: float | None = None, every: float = 0.5, pattern: str = "*") -> dict:
    """Wait until files in a folder (and its subfolders) are added, changed or removed, then say which:
    {"added": [...], "changed": [...], "removed": [...]}. Gives empty lists if time_limit passes first."""
    import time

    base = Path(folder)
    if not base.is_dir():
        raise _not_found(base, "folder")

    def look():
        state = {}
        for p in base.rglob("*"):
            try:
                if p.is_file() and fnmatch.fnmatch(p.name, pattern):
                    info = p.stat()
                    state[os.fspath(p)] = (info.st_mtime_ns, info.st_size)
            except OSError:
                pass
        return state

    before = look()
    deadline = None if time_limit is None else time.perf_counter() + time_limit
    while deadline is None or time.perf_counter() < deadline:
        time.sleep(every)
        now = look()
        if now != before:
            return {"added": sorted(set(now) - set(before)), "removed": sorted(set(before) - set(now)),
                    "changed": sorted(k for k in set(now) & set(before) if now[k] != before[k])}
    return {"added": [], "changed": [], "removed": []}


# ---------------------------------------------------------------- other computers
def _copier(using: str, port):
    from .program import Program

    if using not in ("scp", "rsync"):
        raise choice_error("send_files_to", "using", using, ["scp", "rsync"])
    copier = Program(using)
    if using == "scp":
        copier.add_switch("r")
        if port:
            copier.add_option("P", port)
    else:
        copier.add_switch("a", "partial")
        if port:
            copier.add_option("e", f"ssh -p {port}")
    return copier


def send_files_to(computer: str, *paths, to: str = ".", using: str = "scp", port: int | None = None):
    """Copy files and folders to another computer over ssh (like scp -r): send_files_to("me@server", "reads", to="/data").
    using="rsync" copies only what changed. Gives the Result of the copy."""
    if not paths:
        raise SimplyCommandError('Say what to send: send_files_to("me@server", "file_or_folder", to="/data").')
    for path in paths:
        if not Path(path).exists():
            raise _not_found(path)
    return _copier(using, port).run(*map(os.fspath, paths), f"{computer}:{to}")


def get_files_from(computer: str, *paths, to=".", using: str = "scp", port: int | None = None):
    """Copy files and folders from another computer over ssh: get_files_from("me@server", "/data/results", to="here/").
    Gives the Result of the copy."""
    if not paths:
        raise SimplyCommandError('Say what to get: get_files_from("me@server", "/data/results", to=".").')
    make_folder(to)
    return _copier(using, port).run(*(f"{computer}:{p}" for p in paths), os.fspath(to))
