# test_task_panel.py
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Gtk, GLib
from tavern.task_panel import TavernTaskRow, TavernTaskPanel
from tavern.task_manager import Task, TaskManager, TaskStatus, TaskOperation
from tavern.backend import Package, BrewBackend

def test_task_row_states(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    
    # 1. Install / Running with low progress (pulse path)
    pkg1 = Package({'name': 'ripgrep', 'desc': 'rg', 'versions': {}, 'urls': {}}, 'formula')
    task1 = Task(pkg1, TaskOperation.INSTALL)
    task1.status = TaskStatus.RUNNING
    task1.progress = 0.02
    
    row1 = TavernTaskRow(task1)
    assert row1.task == task1
    assert 'Installing' in row1._title.get_label()
    assert row1._progress_revealer.get_reveal_child() is True
    assert row1._pulse_source is not None
    
    # Trigger pulse manually to cover _do_pulse
    assert row1._do_pulse() is True
    
    # Update progress high (stops pulse)
    task1.progress = 0.5
    row1._on_task_changed()
    assert row1._pulse_source is None
    assert row1._progress_bar.get_fraction() == 0.5
    
    # 2. Upgrade / Completed
    pkg2 = Package({'name': 'git', 'desc': 'git', 'versions': {}, 'urls': {}}, 'formula')
    task2 = Task(pkg2, TaskOperation.UPGRADE)
    task2.status = TaskStatus.COMPLETED
    row2 = TavernTaskRow(task2)
    assert row2._pill_revealer.get_reveal_child() is True
    assert row2._pill.get_label() == 'Done'
    assert row2._done_icon.get_visible() is True
    
    # 3. Remove / Failed
    pkg3 = Package({'name': 'wget', 'desc': 'wget', 'versions': {}, 'urls': {}}, 'formula')
    task3 = Task(pkg3, TaskOperation.REMOVE)
    task3.status = TaskStatus.FAILED
    task3.error_detail = 'Brew failed'
    row3 = TavernTaskRow(task3)
    assert row3._pill.get_label() == 'Failed'
    assert row3._error_icon.get_visible() is True
    assert row3.get_tooltip_text() == 'Brew failed'
    
    # 4. Pending
    pkg4 = Package({'name': 'curl', 'desc': 'curl', 'versions': {}, 'urls': {}}, 'formula')
    task4 = Task(pkg4, TaskOperation.INSTALL)
    task4.status = TaskStatus.PENDING
    row4 = TavernTaskRow(task4)
    assert row4._pill.get_label() == 'In Queue'
    
    # Clean up timeout sources
    row1._stop_pulse()
    row2._stop_pulse()
    row3._stop_pulse()
    row4._stop_pulse()

def test_task_panel_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(GLib, 'get_user_cache_dir', lambda: str(tmp_path))
    backend = BrewBackend()
    mgr = TaskManager(backend)
    
    # Add a task to manager first to cover the initial list-connect loop
    pkg1 = Package({'name': 'ripgrep', 'desc': 'rg', 'versions': {}, 'urls': {}}, 'formula')
    t1 = mgr.submit(pkg1, TaskOperation.INSTALL)
    
    panel = TavernTaskPanel(mgr)
    
    assert panel is not None
    assert panel.panel_stack.get_visible_child_name() == 'tasks'
    assert t1 in panel._rows
    
    # Try adding the same task again to test the duplicate-row early return
    panel._add_row(t1)
    
    # Add a second task to trigger _on_task_added callback
    pkg2 = Package({'name': 'git', 'desc': 'git', 'versions': {}, 'urls': {}}, 'formula')
    t2 = mgr.submit(pkg2, TaskOperation.INSTALL)
    assert t2 in panel._rows
    
    # Complete the task and test finished/clear paths
    t1.status = TaskStatus.COMPLETED
    panel._on_task_finished(mgr, t1)
    assert panel.clear_button.get_visible() is True
    
    # Clear finished
    panel._on_clear_clicked(None)
    assert panel.panel_stack.get_visible_child_name() == 'tasks' # Still has t2 active
    
    # Complete t2 and clear all
    t2.status = TaskStatus.COMPLETED
    panel._on_task_finished(mgr, t2)
    panel._on_clear_clicked(None)
    assert panel.panel_stack.get_visible_child_name() == 'empty'
    assert panel.clear_button.get_visible() is False
    
    # Clean up rows
    for row in panel._rows.values():
        row._stop_pulse()
