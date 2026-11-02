# SPDX-License-Identifier: GPL-3.0-or-later

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from gi.repository import Adw

from tavern.tap_choice_dialog import show_tap_choice

pytestmark = pytest.mark.skipif(
    not hasattr(Adw, 'AlertDialog'), reason='needs libadwaita >= 1.5 for Adw.AlertDialog',
)


def test_first_tap_is_selected_and_install_returns_selected_qualified_name():
    selected = Mock()
    dialog = show_tap_choice(None, SimpleNamespace(name='tool', display_name=None),
                             ('a/tap/tool', 'b/tap/tool'), selected)
    choices = dialog.get_extra_child()
    assert choices.get_selected_row() is choices.get_row_at_index(0)
    assert choices.get_row_at_index(1).get_title() == 'b/tap/tool'
    assert choices.get_row_at_index(1).get_subtitle() == 'from tap: b/tap'
    choices.select_row(choices.get_row_at_index(1))
    dialog.emit('response', 'install')
    selected.assert_called_once_with('b/tap/tool')


@pytest.mark.parametrize('response, options', [('cancel', ('a/tap/tool',)), ('install', ())])
def test_cancel_or_no_selection_does_not_install(response, options):
    selected = Mock()
    dialog = show_tap_choice(None, SimpleNamespace(name='tool', display_name='Tool'),
                             options, selected)
    dialog.emit('response', response)
    selected.assert_not_called()
