# task_panel.py - Bazaar-style task / download manager panel
# SPDX-License-Identifier: GPL-3.0-or-later

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, GLib, Pango
from .task_manager import Task, TaskStatus, TaskOperation, TaskManager


# ── Operation icon names ─────────────────────────────────────────────────────

_OP_ICONS = {
    TaskOperation.INSTALL: 'folder-download-symbolic',
    TaskOperation.REMOVE:  'user-trash-symbolic',
    TaskOperation.UPGRADE: 'software-update-available-symbolic',
}


# ── Single task row ───────────────────────────────────────────────────────────

class TavernTaskRow(Gtk.ListBoxRow):
    """
    Bazaar-style transaction row.

    Layout (horizontal):
      [Op icon 48px]  [Title]
                      [ProgressBar]  ← revealed while RUNNING
                      [status text]  ← e.g. "Downloading…"
                      [Pill row]     ← revealed when NOT running: Waiting/Done/Failed
    """

    __gtype_name__ = 'TavernTaskRow'

    def __init__(self, task, **kwargs):
        super().__init__(**kwargs)
        self._task = task
        self.set_activatable(False)
        self.set_selectable(False)

        # ── Outer box ────────────────────────────────────────────────────────
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        outer.set_margin_top(12)
        outer.set_margin_bottom(12)

        # Op icon
        self._icon = Gtk.Image(pixel_size=48, valign=Gtk.Align.START)
        self._icon.add_css_class('dim-label')
        outer.append(self._icon)

        # Info column
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True,
                       valign=Gtk.Align.CENTER)

        # Title
        self._title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._title.add_css_class('heading')
        info.append(self._title)

        # ── Progress section (visible while RUNNING) ─────────────────────────
        running_now = task.status == TaskStatus.RUNNING
        self._progress_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
            transition_duration=200,
            reveal_child=running_now,
        )
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        progress_box.set_margin_top(4)

        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_hexpand(True)
        self._progress_bar.add_css_class('task-inline-progress')
        progress_box.append(self._progress_bar)

        # Status text below the bar — matches Bazaar's download size label position
        self._progress_label = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self._progress_label.add_css_class('caption')
        self._progress_label.add_css_class('dim-label')
        progress_box.append(self._progress_label)

        self._progress_revealer.set_child(progress_box)
        info.append(self._progress_revealer)

        # ── Status pill row (visible when NOT running) ───────────────────────
        self._pill_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
            transition_duration=200,
            reveal_child=False,
        )
        pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        pill_box.set_margin_top(4)

        self._pill = Gtk.Label(xalign=0)
        self._pill.add_css_class('caption')
        self._pill.add_css_class('task-status-pill')
        pill_box.append(self._pill)

        self._pill_revealer.set_child(pill_box)
        info.append(self._pill_revealer)

        outer.append(info)

        # ── Right indicator (spinner / done / error) ─────────────────────────
        right = Gtk.Box(valign=Gtk.Align.CENTER)
        right.set_margin_start(4)

        self._spinner = Adw.Spinner()
        self._spinner.set_size_request(22, 22)
        right.append(self._spinner)

        self._done_icon = Gtk.Image(icon_name='object-select-symbolic', pixel_size=22)
        self._done_icon.add_css_class('success')
        self._done_icon.set_visible(False)
        right.append(self._done_icon)

        self._error_icon = Gtk.Image(icon_name='dialog-error-symbolic', pixel_size=22)
        self._error_icon.add_css_class('error')
        self._error_icon.set_visible(False)
        right.append(self._error_icon)

        outer.append(right)
        self.set_child(outer)

        self._pulse_source = None

        # ── Connect task signals ──────────────────────────────────────────────
        task.connect('notify::status',      self._on_task_changed)
        task.connect('notify::progress',    self._on_task_changed)
        task.bind_property('status-text',   self._progress_label, 'label', GObject.BindingFlags.SYNC_CREATE)
        self._update()

    @property
    def task(self):
        return self._task

    def _on_task_changed(self, *_):
        self._update()

    def _update(self):
        t = self._task

        # Icon
        self._icon.set_from_icon_name(_OP_ICONS.get(t.operation, 'folder-download-symbolic'))

        # Title
        self._title.set_label(t.title)

        running = t.status == TaskStatus.RUNNING
        pending = t.status == TaskStatus.PENDING
        done    = t.status == TaskStatus.COMPLETED
        failed  = t.status == TaskStatus.FAILED

        # Progress section
        self._progress_revealer.set_reveal_child(running)
        if running:
            if t.progress > 0.05:
                self._stop_pulse()
                self._progress_bar.set_fraction(t.progress)
            else:
                self._start_pulse()
        else:
            self._stop_pulse()

        # Pill section
        self._pill_revealer.set_reveal_child(not running)
        if pending:
            self._pill.set_label('In Queue')
            self._set_pill_style('pill-waiting')
        elif done:
            self._pill.set_label('Done')
            self._set_pill_style('pill-done')
        elif failed:
            self._pill.set_label('Failed')
            self._set_pill_style('pill-error')
            if t.error_detail:
                self.set_tooltip_text(t.error_detail)

        # Right indicator
        active = pending or running
        self._spinner.set_visible(active)
        self._done_icon.set_visible(done)
        self._error_icon.set_visible(failed)

    def _start_pulse(self):
        if self._pulse_source is None:
            self._pulse_source = GLib.timeout_add(80, self._do_pulse)

    def _stop_pulse(self):
        if self._pulse_source is not None:
            GLib.source_remove(self._pulse_source)
            self._pulse_source = None

    def _do_pulse(self):
        self._progress_bar.pulse()
        return True  # keep firing

    def _set_pill_style(self, new_class):
        for cls in ('pill-waiting', 'pill-done', 'pill-error'):
            self._pill.remove_css_class(cls)
        self._pill.add_css_class(new_class)


# ── Panel dialog ──────────────────────────────────────────────────────────────

@Gtk.Template(resource_path='/org.tunaos.tavern/task-panel.ui')
class TavernTaskPanel(Adw.Dialog):
    """Dialog listing all active and recent tasks."""

    __gtype_name__ = 'TavernTaskPanel'

    panel_stack   = Gtk.Template.Child()
    task_list_box = Gtk.Template.Child()
    clear_button  = Gtk.Template.Child()

    def __init__(self, task_manager=None, **kwargs):
        super().__init__(**kwargs)
        self._task_manager = task_manager
        self._rows = {}  # task -> TavernTaskRow

        self.clear_button.connect('clicked', self._on_clear_clicked)

        if task_manager:
            self._connect_manager(task_manager)

    def _connect_manager(self, mgr):
        mgr.connect('task-added',    self._on_task_added)
        mgr.connect('task-finished', self._on_task_finished)
        for task in mgr.tasks:
            self._add_row(task)
        self._refresh_ui()

    def _on_task_added(self, mgr, task):
        self._add_row(task)
        self._refresh_ui()

    def _on_task_finished(self, mgr, task):
        self._refresh_ui()

    def _add_row(self, task):
        if task in self._rows:
            return
        row = TavernTaskRow(task)
        self._rows[task] = row
        self.task_list_box.prepend(row)

    def _refresh_ui(self):
        has_tasks = bool(self._rows)
        self.panel_stack.set_visible_child_name('tasks' if has_tasks else 'empty')
        has_done = any(
            t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            for t in self._rows
        )
        self.clear_button.set_visible(has_done)

    def _on_clear_clicked(self, _button):
        finished = [t for t in self._rows if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)]
        for task in finished:
            row = self._rows.pop(task)
            self.task_list_box.remove(row)
        self._refresh_ui()
