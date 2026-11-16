"""Step 5: a program that talks with the person at the terminal: questions, choices, a password,
a progress bar and colour.

Try in the terminal:
    python 05_talking_to_people.py
    python 05_talking_to_people.py --name Ann --language Norwegian --yes   (no questions: good for scripts)

The rule worth keeping: everything the program asks can also be given as an option, so the same
program works for a person and inside a script, where nobody is there to answer.
"""

import time

import simplycommand as scmd

GREETINGS = {"English": "Welcome", "Norwegian": "Velkommen", "German": "Willkommen", "Hindi": "Swagat hai"}


def set_up(name: str | None = None, language: str | None = None, steps: int = 20, yes: bool = False):
    """Set up a new user, asking for what was not given.
    name: your name (asked if not given)
    language: English, Norwegian, German or Hindi (asked if not given)
    steps: how many set-up steps to show
    yes (-y): do not ask before starting
    """
    name = name or scmd.ask("Your name", default="friend")
    language = language or scmd.ask_to_choose("Which language?", list(GREETINGS), default="English")
    if language not in GREETINGS:
        raise scmd.SimplyCommandError(f'"{language}" is not one of: {", ".join(GREETINGS)}.')
    if not yes and not scmd.ask_yes_or_no("Start the set-up?", default=True):
        return "Nothing was done."

    for _ in scmd.show_progress(range(steps), label="Setting up"):
        time.sleep(0.05)  # stands in for real work

    scmd.write_in_colour(f"{GREETINGS[language]}, {name}!", "green", bold=True)
    return None  # nothing more to print


if __name__ == "__main__":
    scmd.make_command_line_program(set_up)
