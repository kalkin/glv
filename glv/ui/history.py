# pylint: disable=missing-docstring
#
# Copyright (c) 2018-2020 Bahtiar `kalkin-` Gadimov.
#
# This file is part of Git Log Viewer
# (see https://github.com/kalkin/git-log-viewer).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#
import logging
import os
import sys
from threading import Thread
from typing import Any, List, Optional

from prompt_toolkit import shortcuts
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (BufferControl, Dimension, HSplit, UIContent,
                                   Window)
from prompt_toolkit.layout.controls import SearchBufferControl
from prompt_toolkit.search import SearchDirection, SearchState
from prompt_toolkit.widgets import SearchToolbar

from glv import NoPathMatches, NoRevisionMatches, Repo, utils
from glv.commit import Commit, CommitNotFound, child_history, follow, is_folded
from glv.ui.log_entry import LogEntry
from glv.ui.status import STATUS, STATUS_WINDOW
from glv.utils import parse_args

LOG = logging.getLogger('glv')


class History(UIContent):
    # pylint: disable=too-many-instance-attributes
    def __init__(self, arguments: dict) -> None:
        try:
            self.path, self.revision, self.files = parse_args(**arguments)
            repo = Repo(path=self.path)

            path = repo.working_dir.replace(os.path.expanduser('~'), '~', 1)
            self.working_dir = repo.working_dir
            revision = self.revision[0]
            if self.revision == 'HEAD':
                revision = repo._nrepo.head.ref.name
            title = '%s \uf418 %s' % (path.rstrip('/'), revision)

            shortcuts.set_title('%s - Git Log Viewer' % title)
        except NoRevisionMatches:
            print('No revisions match the given arguments.', file=sys.stderr)
            sys.exit(1)
        except NoPathMatches:
            print("No paths match the given arguments.", file=sys.stderr)
            sys.exit(1)

        self.date_max_len = 0
        self.name_max_len = 0
        self._repo = repo
        self.line_count = self._repo.count_commits(self.revision[0])
        self.commit_list: List[Commit] = []
        self.log_entry_list: List[Commit] = []
        self.search_state: Optional[SearchState] = None
        self._search_thread: Optional[Thread] = None
        super().__init__(line_count=self.line_count,
                         get_line=self.get_line,
                         show_cursor=False)
        self.fill_up(utils.screen_height())

    def apply_search(self,
                     search_state: SearchState,
                     include_current_position=True,
                     count=1):
        if self._search_thread is not None and self._search_thread.is_alive():
            try:
                self._search_thread._stop()  # pylint: disable=protected-access
            except Exception:  # nosec pylint: disable=broad-except
                pass
            finally:
                STATUS.clear()

        args = (search_state, include_current_position, count)
        self._search_thread = Thread(target=self.search,
                                     args=args,
                                     daemon=True)
        self._search_thread.start()

    def current(self, index: int) -> Optional[Commit]:
        LOG.debug("Fetching current for index %d", index)
        try:
            commit = self.commit_list[index]
            return commit
        except IndexError:
            LOG.info("No index %d in commit list", index)
            return None

    def search(self,
               search_state: SearchState,
               include_current_position=True,
               count=1):
        LOG.debug('applying search %r, %r, %r', search_state,
                  include_current_position, count)
        self.search_state = search_state
        index = self.cursor_position.y
        new_position = self.cursor_position.y
        LOG.debug('Current position %r', index)
        needle = self.search_state.text
        STATUS.set_status("Searching for '%s'" % needle)
        if self.search_state.direction == SearchDirection.FORWARD:
            if not include_current_position:
                index += 1
            while True:
                try:
                    commit = self.commit_list[index]
                except IndexError:
                    if not self.fill_up(utils.screen_height()):
                        break

                    commit = self.commit_list[index]

                if needle in commit.short_id or needle in commit.subject \
                        or needle in commit.author_name \
                        or any(needle in haystack for haystack in commit.branches):
                    new_position = index
                    break

                index += 1
        else:
            if not include_current_position and index > 0:
                index -= 1
            while index >= 0:
                commit = self.commit_list[index]
                if needle in commit.short_id() or needle in commit.subject \
                        or needle in commit.author_name():
                    new_position = index
                    break

                index -= 1

        if new_position != self.cursor_position.y:
            self.cursor_position = Point(x=self.cursor_position.x, y=index)
        STATUS.clear()

    def get_line(self, line_number: int) -> List[tuple]:  # pylint: disable=method-hidden
        length = len(self.commit_list)
        if length - 1 < line_number:
            amount = line_number - length + 1
            self.fill_up(amount)

        try:
            commit = self.commit_list[line_number]
        except IndexError:
            return [("", "")]

        return self._render_commit(commit, line_number)

    def _render_commit(self, commit: Commit, line_number: int) -> List[tuple]:
        try:
            entry = self.log_entry_list[line_number]
            entry.search_state = self.search_state
        except KeyError:
            self.log_entry_list[line_number] = LogEntry(
                commit, self.working_dir, self.search_state)
            entry = self.log_entry_list[line_number]
            entry.search_state = self.search_state

        tmp = [
            entry.short_id_colored,
            entry.author_date_short_colored(self.date_max_len),
            entry.author_name_short_colored(self.name_max_len),
            entry.icon_colored, entry.type_colored, entry.modules_colored,
            entry.subject_colored, entry.references_colored
        ]
        result: List[tuple] = []
        for sth in tmp:
            if isinstance(sth, tuple):
                result += [sth, ('', ' ')]
            else:
                result += sth
                result += [('', ' ')]

        if line_number == self.cursor_position.y:
            result = [('reverse ' + x[0], x[1]) for x in result]

        return [(x[0], x[1]) for x in result]

    def toggle_fold(self, line_number):
        commit = self.commit_list[line_number]
        if not commit.is_merge:
            return

        if is_folded(self.commit_list, line_number):
            self._unfold(line_number, commit)
        else:
            self._fold(line_number + 1, commit)

    def _fold(self, pos: int, commit: Commit) -> Any:
        LOG.info('Expected level %s', commit.level)
        for _, cur in enumerate(self.commit_list[pos:]):
            LOG.info('Checking %s', cur)
            if commit.level < cur.level:
                del self.commit_list[pos]
                del self.log_entry_list[pos]
            else:
                break

    def _unfold(self, line_number: int, commit: Commit) -> Any:
        index = 1
        for _ in child_history(self.working_dir, commit):
            entry = LogEntry(_, self.working_dir, self.search_state)
            if len(entry.author_rel_date) > self.date_max_len:
                self.date_max_len = len(entry.author_rel_date)
            if len(entry.author_name) > self.name_max_len:
                self.name_max_len = len(entry.author_name)
            self.commit_list.insert(line_number + index, _)
            self.log_entry_list.insert(line_number + index, entry)
            index += 1

        self.line_count += index

    def fill_up(self, amount: int) -> int:
        if amount <= 0:
            raise ValueError('Amount must be ≤ 0')

        commits = self._repo.iter_commits(
            rev_range=self.revision[0],
            skip=len([x for x in self.commit_list if x.level == 0]),
            max_count=amount,
            paths=self.files)
        for commit in commits:
            self.commit_list.append(commit)
            entry = LogEntry(commit, self.working_dir, self.search_state)
            self.log_entry_list.append(entry)
            if len(entry.author_rel_date) > self.date_max_len:
                self.date_max_len = len(entry.author_rel_date)
            if len(entry.author_name) > self.name_max_len:
                self.name_max_len = len(entry.author_name)
        return len(commits)


class HistoryControl(BufferControl):
    def __init__(self, search_buffer_control: SearchBufferControl,
                 key_bindings: Optional[KeyBindings], arguments: dict) -> None:
        buffer = Buffer(name='history')
        self.content = History(arguments)
        buffer.apply_search = self.content.apply_search  # type: ignore
        super().__init__(buffer=buffer,
                         search_buffer_control=search_buffer_control,
                         focus_on_click=True,
                         key_bindings=key_bindings)

    def is_focusable(self) -> bool:
        return True

    @property
    def current_line(self) -> int:
        return self.content.cursor_position.y

    def create_content(self, width, height, preview_search=False):
        return self.content

    def current(self) -> Optional[Commit]:
        return self.content.current(self.current_line)

    @property
    def working_dir(self) -> str:
        return self.content.working_dir

    def move_cursor_down(self):
        old_point = self.content.cursor_position
        if old_point.y + 1 < self.content.line_count:
            new_position = Point(x=old_point.x, y=old_point.y + 1)
            self.content.cursor_position = new_position

    def move_cursor_up(self):
        old_point = self.content.cursor_position
        if old_point.y > 0:
            new_position = Point(x=old_point.x, y=old_point.y - 1)
            self.content.cursor_position = new_position

    def goto_line(self, line_number):
        if line_number < 0:
            line_number = self.content.line_count + 1 - line_number
            if line_number < 0:
                line_number = 0
        elif line_number >= self.content.line_count:
            line_number = self.content.line_count - 1

        if self.current_line != line_number:
            old_point = self.content.cursor_position
            new_position = Point(x=old_point.x, y=line_number)
            self.content.cursor_position = new_position

    def goto_last(self):
        old_point = self.content.cursor_position
        if old_point.y < self.content.line_count:
            new_position = Point(x=old_point.x, y=self.content.line_count - 1)
            self.content.cursor_position = new_position

    def toggle_fold(self, line_number):
        self.content.toggle_fold(line_number)

    def is_folded(self, line_number: int) -> bool:
        commit = self.content.commit_list[line_number]
        if commit.is_merge:
            return is_folded(self.content.commit_list, line_number)
        return False

    def is_foldable(self, line_number: int) -> bool:
        commit = self.content.commit_list[line_number]
        return commit.is_merge

    def is_child(self, line_number: int) -> bool:
        commit = self.content.commit_list[line_number]
        return commit.level > 0

    def go_to_parent(self, line_number: int):
        commit = self.content.commit_list[line_number]
        if commit.level > 0 and line_number > 0:
            i = line_number - 1
            while i >= 0:
                candidat = self.content.commit_list[i]
                if candidat.level < commit.level:
                    self.goto_line(i)
                    break
                i -= 1

    def is_link(self, line_number: int) -> bool:
        commit = self.content.commit_list[line_number]
        return commit.is_commit_link

    def go_to_link(self, line_number: int):
        try:
            result = follow(self.working_dir, self.content.commit_list,
                            line_number)

            if result >= len(self.content.log_entry_list):
                # sync commit_list with log_entry_list
                pos = len(self.content.log_entry_list)
                for commit in self.content.commit_list[pos:]:
                    entry = LogEntry(commit, self.working_dir,
                                     self.content.search_state)
                    self.content.log_entry_list.append(entry)
            self.goto_line(result)
        except CommitNotFound:
            pass

    @property
    def path(self) -> str:
        return self.path


class HistoryContainer(HSplit):
    def __init__(self, key_bindings, arguments, right_margins=None):
        search = SearchToolbar(vi_mode=True)
        log_view = HistoryControl(search.control,
                                  key_bindings=key_bindings,
                                  arguments=arguments)
        window = Window(content=log_view, right_margins=right_margins)
        super().__init__([window, search, STATUS_WINDOW])

    def preferred_width(self, max_available_width: int) -> Dimension:
        _min = 40
        preferred = 80
        if max_available_width / 2 >= 80:
            preferred = max_available_width / 2

        return Dimension(min=_min, preferred=preferred)
