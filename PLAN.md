# simplycommand: design plan

*Status: version 0.3.0: everything subprocess can do, plus files, terminals, limits, remote, containers and conda; 115 tests: all 109 that apply to Windows pass there, all 112 that apply to Linux pass there. Not yet on GitHub or PyPI.*

## 1. The idea

Like simplydata, simplycommand is **a dictionary, not a new engine**. `subprocess` starts the
programs, `argparse` reads the terminal, `shutil`/`shlex` find and split. simplycommand
translates plain words into the right calls with the right settings, and that translation
is what the tests check.

- A program is an **object**: build it up step by step, look at it (`show_command`), run it.
- A run gives a **Result** that says in one sentence what happened.
- Errors say what went wrong, guess what was meant, and say what to do.
- Your own command-line program is a **class**: each method is a command.

## 2. Grammar (the same patterns as simplydata)

| Pattern | Words |
|---|---|
| `add_` / `remove_` + thing changes the program | `add_words`, `add_option`, `add_switch`, `add_options`, `remove_option`, `remove_words` |
| `set_` / `use_` sets how it runs | `set_folder`, `set_environment`, `set_time_limit`, `use_option_style`, `use_input_text`, `use_input_file` |
| `save_..._to` sends a stream into a file; `save_` on a result writes a file | `save_output_to`, `save_errors_to`, `result.save_output` |
| `show_` / `hide_` look without changing | `show_command`, `show_output`, `show_output_while_running`, `hide_output_while_running` |
| `get_` takes a piece out | `get_command_line`, `get_output_lines`, `get_output_as_rows`, `get_output_as_json` |
| `find_` answers a question in a sentence | `find_program`, `find_where_installed`, `find_lines_with` |
| `make_` only makes something new | `make_subcommand`, `make_command_line_program` |
| `start_` / `stop_` begin and end something that lasts | `start_in_background`, `start_log_in`, `start_showing_commands`, `stop_log` |

Options: Python names become the tool's own option names through **one example of its style**
(`"--long-name"`, `"-long_name"`, `"--long-name=value"`, `"/name"`). True is a switch,
False/None leaves it out, a list repeats it, a trailing `_` allows Python words (`in_=`).

## 3. Road to 100% of the command line

### Done in 0.2.0
- [x] `put_errors_into_output()` (2>&1), `accept_exit_codes(0, 1)`, `use_clean_environment()`
- [x] `use_text_encoding(...)`, `result.get_output_as_bytes()`, `result.describe_exit()` (signals by name)
- [x] `run_in_this_terminal()`, `keep_input_open()` + `running.send_text / wait_for_text / close_input`
- [x] `do_with_each_line(function)`, `try_again_if_it_fails(times, wait)`
- [x] whole process trees are stopped (taskkill /T on Windows, process groups elsewhere); `stop(gently=True)`
- [x] `set_priority("low")`, `hide_window()`, Ctrl+C stops the programs too
- [x] `run_async`, `scmd.run_together_async`; `run_in_shell(shell="bash" | "powershell" | ...)`
- [x] `set_computer("me@server")` (ssh), `use_conda_environment`, `use_container` (docker, podman,
      apptainer, singularity), `use_python_environment`; they can be joined
- [x] files and folders: `make_folder`, `copy_file`, `copy_folder`, `move_file`, `move_folder`, `remove_file`,
      `remove_folder`, `find_files`, `find_size_of`, `get/set_current_folder`, `pack_into`, `unpack`, `download_file`
- [x] names from subprocess/shutil/os (`Popen`, `rmtree`, `glob` ...) point to the simplycommand word
- [x] `CommandLineProgram`: `__init__` options for every command, short letters `(-m)`, `Literal[...]` choices,
      `version`, lists and dicts printed line by line

### Done in 0.3.0
- [x] pseudo-terminal: `run_in_pseudo_terminal()` (pty on Linux/macOS, ConPTY through the `terminal` extra on Windows)
- [x] `set_memory_limit`, `set_cpu_time_limit`; `result.cpu_seconds`, `result.peak_memory_mb`
      (job objects on Windows, rlimit and os.wait4 on Linux/macOS)
- [x] `running.send_signal(any)`, `start_in_own_group`, `start_and_leave_running`, `run_as_administrator`,
      `run_as_user`, `set_umask`, `share_open_files`, `do_before_start`, `use_program_file`,
      `use_subprocess_settings(**any Popen setting)`
- [x] `save_output_to(..., also_keep=True)` (tee), `send_errors_to`, `remove_environment_variable`, `add_files_matching`
- [x] files: `set_permissions`, `make_runnable`, `set_owner`, `make_link`, `find_where_link_points`, `get_file_dates`,
      `find_free_space`, `make_temporary_folder/file`, `wait_for_change_in`, `send_files_to`, `get_files_from`,
      full-path patterns in `find_files`
- [x] talking: `ask`, `ask_yes_or_no`, `ask_for_password`, `ask_to_choose`, `write_in_colour`, `colour_text`, `show_progress`
- [x] `CommandLineProgram`: command groups (a class inside the class), `only_one_of`, `environment_prefix`,
      `defaults_file` (JSON or TOML), tab completion through the `completion` extra
- [x] tested on Windows (109 pass, 6 are Linux-only) and on Linux (Ubuntu in WSL, Python 3.14: 112 pass, 3 are Windows-only); CI file for Windows, macOS, Linux

### Still open
- [ ] run the CI on macOS (the code follows Python's documented macOS behaviour, but it has not been run there)
- [ ] test `set_computer`, `send_files_to` and `use_container` against a real server and Docker
      (the command words are tested; the tools themselves are ssh, scp, rsync and docker)
- [ ] `run_as_administrator` on Windows shows the UAC prompt, so it cannot run in automatic tests
- [ ] old names keep working for one release with a one-line note, once something is renamed

### Release
- [ ] GitHub repository, CI on Windows, macOS and Linux, Python 3.10 to 3.13
- [ ] PyPI release (check the name `simplycommand` is free first)
- [ ] a manual and dictionary built from the code, as in simplydata
