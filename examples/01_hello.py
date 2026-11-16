"""Step 1: the smallest command-line program is one function.

Try in the terminal:
    python 01_hello.py Ann
    python 01_hello.py Ann --times 3 --shout
    python 01_hello.py Ann -t 2
    python 01_hello.py --help

What simplycommand reads from the function:
    name: str           no default  -> a word given in order (here: Ann)
    times: int = 1      a default   -> an option, --times 3 (turned into a whole number)
    shout: bool = False False       -> a switch, --shout (on when given)
    the docstring       -> the text of --help; "times (-t): ..." also gives the short letter -t
"""

import simplycommand as scmd


def hello(name: str, times: int = 1, shout: bool = False):
    """Say hello to someone.
    name: who to greet
    times (-t): how many times to say it
    shout: write it in capital letters
    """
    text = f"Hello, {name}!"
    if shout:
        text = text.upper()
    return [text] * times  # what the function gives back is printed; a list one line at a time


if __name__ == "__main__":
    scmd.make_command_line_program(hello)
