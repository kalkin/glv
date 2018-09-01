#!/usr/bin/env python3

# pylint: disable=missing-docstring,fixme

import os
from datetime import datetime


from line import Commit, Foldable, LastCommit, Repo, InitialCommit
import babel.dates
from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Container, HSplit
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea

HISTORY: list = []

TEXTFIELD = TextArea(read_only=True, wrap_lines=False)
# Global key bindings.
BINDINGS = KeyBindings()

ROOT_CONTAINER: Container = HSplit([
    TEXTFIELD,
])

APPLICATION = Application(
    layout=Layout(ROOT_CONTAINER, ),
    key_bindings=BINDINGS,
    mouse_support=True,
    full_screen=True)


def commit_type(line: Commit) -> str:
    ''' Helper method for displaying commit type.  '''
    # TODO Add support for ocotopus branch display
    if isinstance(line, Foldable):
        return "●─╮"
    elif isinstance(line, InitialCommit):
        return "◉  "
    elif isinstance(line, LastCommit):
        return "✂  "

    return "●  "


def relative_date(commit: Commit) -> str:
    ''' Translates a unique timestamp to a relative and short date string '''
    # pylint: disable=invalid-name
    timestamp: int = commit.committer.time
    t = timestamp
    delta = datetime.now() - datetime.fromtimestamp(t)
    return babel.dates.format_timedelta(delta, format='short').strip('.')


@BINDINGS.add('c-c')
def _(_):
    get_app().exit(result=False)


def format_commit(line: Commit) -> str:
    return " ".join([commit_type(line), str(line)])


def current_row(textarea: TextArea) -> int:
    document: Document = textarea.document
    return document.cursor_position_row


def current_line(pos: int) -> Commit:
    return HISTORY[pos]


@BINDINGS.add('enter')
def toggle_fold(_):
    row = current_row(TEXTFIELD)
    line: Commit = current_line(row)
    point = TEXTFIELD.buffer.cursor_position
    if isinstance(line, Foldable):
        if line.is_folded:
            fold_open(line, row)
        else:
            fold_close(line, row)

    TEXTFIELD.buffer.cursor_position = point


def fold_close(line: Foldable, index: int):
    lines = TEXTFIELD.text.splitlines()
    line.fold()
    index += 1
    while line.child_log():
        del lines[index]
        del HISTORY[index]
    TEXTFIELD.text = "\n".join(lines)


def fold_open(start: Foldable, index: int):
    lines = TEXTFIELD.text.splitlines()
    start.unfold()
    for commit in start.child_log():
        level = commit.level * '  '
        HISTORY.insert(index, commit)
        msg = level + format_commit(commit)
        lines.insert(index + 1, msg)
        HISTORY.insert(index + 1, commit)
        index += 1
    TEXTFIELD.text = "\n".join(lines)


def cli():
    repo = Repo(os.getcwd())
    for commit in repo.walker():
        msg = format_commit(commit)
        HISTORY.append(commit)
        TEXTFIELD.text += msg + "\n"
    APPLICATION.run()


if __name__ == '__main__':
    cli()
