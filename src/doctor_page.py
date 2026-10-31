"""GTK presentation and queued fixes for Homebrew diagnostics."""
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext
import threading

from gi.repository import Adw, GLib, Gtk

from .doctor import DoctorService, severity_groups, select_after_reload
from .brew_commands import run_read, transcript

_ = gettext.gettext


def _run_doctor():
    from .brew_env import is_brew_available
    if not is_brew_available():
        from .doctor import DoctorError
        raise DoctorError(_('Homebrew is not installed.'))
    result = run_read(('doctor', '--json'), timeout=60)
    if result.returncode and any(message in transcript(result).lower() for message in
                                ('invalid option: --json', 'unknown option: --json')):
        # Pre-7 Homebrew: warnings are printed to stderr in the text format.
        result = run_read(('doctor',), timeout=60)
        result.stdout = transcript(result)
        result.stderr = ''
    else:
        result.doctor_json = True
    return result


@Gtk.Template(resource_path='/org.tunaos.tavern/doctor-page.ui')
class TavernDoctorPage(Adw.Bin):
    __gtype_name__ = 'TavernDoctorPage'

    run_button = Gtk.Template.Child()
    copy_button = Gtk.Template.Child()
    spinner = Gtk.Template.Child()
    status_label = Gtk.Template.Child()
    error_label = Gtk.Template.Child()
    findings_list = Gtk.Template.Child()
    detail_placeholder = Gtk.Template.Child()
    detail_content = Gtk.Template.Child()
    detail_title = Gtk.Template.Child()
    detail_severity = Gtk.Template.Child()
    detail_body = Gtk.Template.Child()
    detail_blocks = Gtk.Template.Child()
    raw_expander = Gtk.Template.Child()
    raw_view = Gtk.Template.Child()
    config_button = Gtk.Template.Child()
    sidebar_box = Gtk.Template.Child()
    sidebar_separator = Gtk.Template.Child()

    def __init__(self, service=None, task_manager=None, **kwargs):
        super().__init__(**kwargs)
        self._service = service if service is not None else DoctorService(_run_doctor)
        self._report = None
        self._busy = False
        self._rows = {}
        self._task_manager = task_manager
        self._fix_tasks = {}
        self._fix_widgets = {}
        self._refresh_pending = False
        self.run_button.connect('clicked', lambda _button: self.refresh(force=True))
        self.copy_button.connect('clicked', self._copy_output)
        self.config_button.connect('clicked', self._show_config)
        self.connect('map', lambda _page: self.refresh())
        self.findings_list.connect('row-selected', self._on_row_selected)
        self._render_detail(None)

    def set_task_manager(self, task_manager):
        self._task_manager = task_manager
        for key in self._fix_widgets:
            self._update_fix(key)

    def refresh(self, force=False):
        if self._busy:
            return
        self._busy = True
        self.run_button.set_sensitive(False)
        self.spinner.start()
        self.error_label.set_visible(False)
        self.status_label.set_label(_('Re-checking…') if self._report else _('Running brew doctor…'))

        def worker():
            try:
                report = self._service.load(force=force)
            except Exception as error:
                GLib.idle_add(self._complete, None, str(error))
            else:
                GLib.idle_add(self._complete, report, None)

        threading.Thread(target=worker, daemon=True, name='tavern-doctor').start()

    def _complete(self, report, error):
        self._busy = False
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh(force=True)
            return False
        self.spinner.stop()
        self.run_button.set_sensitive(True)
        self.run_button.set_label(_('Run Again'))
        if error is not None:
            self.status_label.set_label(
                _('Check failed — previous report shown') if self._report else _('The check could not be completed')
            )
            self.error_label.set_label(error)
            self.error_label.set_visible(True)
            return False

        self._report = report
        self.error_label.set_visible(bool(report.warnings))
        self.error_label.set_label(report.warnings)
        self.status_label.set_label(_('Warnings found') if report.issues else _('No problems found'))
        if report.tier is not None:
            self.status_label.set_label(self.status_label.get_label() + ' — ' +
                                        _('Support tier: {tier}').format(tier=report.tier))
        self.raw_view.get_buffer().set_text(report.raw_output)
        self.raw_expander.set_visible(True)
        self.copy_button.set_sensitive(bool(report.raw_output))
        self._build_list(report)
        return False

    def _build_list(self, report):
        """Rebuild the grouped list and revalidate the selection.

        The list is grouped by severity in display order. The previous selection is
        captured from the live list before it is rebuilt, then kept when its issue is
        still present (it may have moved), dropped when it resolved, and defaults to
        the first issue otherwise. The list grabs focus so up/down navigates findings.
        """
        previous = self._rows.get(self.findings_list.get_selected_row())
        previous_content_id = previous.content_id if previous is not None else None

        while child := self.findings_list.get_first_child():
            self.findings_list.remove(child)
        self._rows.clear()

        severities = {'warning': _('Warning'), 'error': _('Error'),
                      'unsupported': _('Unsupported configuration')}
        prefix_icons = {
            'warning': 'dialog-warning-symbolic',
            'error': 'dialog-error-symbolic',
            'unsupported': 'dialog-error-symbolic',
        }
        for _key, group in severity_groups(report.issues):
            for issue in group:
                row = Adw.ActionRow(title=issue.title,
                                    subtitle=severities.get(issue.severity, issue.severity),
                                    use_markup=False)
                icon = Gtk.Image.new_from_icon_name(prefix_icons.get(issue.severity, 'dialog-warning-symbolic'))
                if issue.severity in ('error', 'unsupported'):
                    icon.add_css_class('error')
                else:
                    icon.add_css_class('warning')
                row.add_prefix(icon)
                self.findings_list.append(row)
                self._rows[row] = issue

        has_issues = bool(report.issues)
        self.findings_list.set_visible(has_issues)
        self.sidebar_box.set_visible(has_issues)
        self.sidebar_separator.set_visible(has_issues)

        desired = select_after_reload(previous_content_id, report.issues)
        selected_row = None
        if desired is not None:
            for row, issue in self._rows.items():
                if issue.content_id == desired.content_id:
                    selected_row = row
                    break
        self.findings_list.unselect_all()
        if selected_row is not None:
            self.findings_list.select_row(selected_row)
            self._render_detail(self._rows.get(selected_row))
        if report.issues:
            self.findings_list.grab_focus()
        else:
            self._render_detail(None)

    def _on_row_selected(self, _list_box, row):
        self._render_detail(self._rows.get(row) if row is not None else None)

    def _clear_detail_blocks(self):
        self._fix_widgets.clear()
        while child := self.detail_blocks.get_first_child():
            self.detail_blocks.remove(child)

    def _copy_text(self, text):
        clipboard = self.get_clipboard()
        if clipboard is not None:
            clipboard.set(text)

    def _render_blocks(self, blocks):
        for block in blocks:
            if block.caption:
                caption_lbl = Gtk.Label(label=block.caption, xalign=0.0, wrap=True)
                caption_lbl.add_css_class('heading')
                caption_lbl.set_margin_top(6)
                self.detail_blocks.append(caption_lbl)

            if block.type == 'prose':
                text = '\n'.join(block.value)
                if text.strip():
                    lbl = Gtk.Label(label=text, xalign=0.0, wrap=True, selectable=True)
                    lbl.add_css_class('body')
                    self.detail_blocks.append(lbl)

            elif block.type == 'command':
                for step in block.value:
                    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                    card.add_css_class('card')
                    card.set_margin_top(4)
                    card.set_margin_bottom(4)

                    inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                    inner.set_margin_start(14)
                    inner.set_margin_end(10)
                    inner.set_margin_top(10)
                    inner.set_margin_bottom(10)

                    term_icon = Gtk.Image.new_from_icon_name('utilities-terminal-symbolic')
                    term_icon.set_valign(Gtk.Align.CENTER)
                    term_icon.add_css_class('dim-label')
                    inner.append(term_icon)

                    cmd_lbl = Gtk.Label(label=step.display_command, xalign=0.0, wrap=True, selectable=True)
                    cmd_lbl.set_hexpand(True)
                    cmd_lbl.add_css_class('monospace')
                    inner.append(cmd_lbl)

                    copy_btn = Gtk.Button.new_from_icon_name('edit-copy-symbolic')
                    copy_btn.set_valign(Gtk.Align.CENTER)
                    copy_btn.set_tooltip_text(_('Copy Command'))
                    copy_btn.add_css_class('flat')
                    copy_btn.connect('clicked', lambda _btn, cmd=step.display_command: self._copy_text(cmd))
                    inner.append(copy_btn)

                    card.append(inner)

                    if block.is_runnable:
                        self._add_fix_controls(inner, card, block)
                    else:
                        note = (_('Requires administrator privileges — run in Terminal')
                                if step.needs_admin else _('Run in Terminal — copy this command'))
                        label = Gtk.Label(label=note, xalign=0.0, wrap=True)
                        label.add_css_class('caption')
                        label.set_margin_start(14)
                        label.set_margin_end(14)
                        label.set_margin_bottom(8)
                        card.append(label)

                    self.detail_blocks.append(card)

            elif block.type == 'data':
                if block.value:
                    data_list = Gtk.ListBox()
                    data_list.add_css_class('boxed-list')
                    data_list.set_selection_mode(Gtk.SelectionMode.NONE)

                    for item in block.value:
                        row = Adw.ActionRow(title=item, selectable=True, use_markup=False)
                        copy_btn = Gtk.Button.new_from_icon_name('edit-copy-symbolic')
                        copy_btn.set_valign(Gtk.Align.CENTER)
                        copy_btn.set_tooltip_text(_('Copy Item'))
                        copy_btn.add_css_class('flat')
                        copy_btn.connect('clicked', lambda _btn, text=item: self._copy_text(text))
                        row.add_suffix(copy_btn)
                        data_list.append(row)

                    self.detail_blocks.append(data_list)

            elif block.type == 'link':
                if block.value:
                    link_list = Gtk.ListBox()
                    link_list.add_css_class('boxed-list')
                    link_list.set_selection_mode(Gtk.SelectionMode.NONE)

                    for link in block.value:
                        row = Adw.ActionRow(
                            title=link.url,
                            subtitle=_('Action required') if link.role == 'action' else _('Reference documentation'),
                            use_markup=False,
                        )
                        link_btn = Gtk.LinkButton.new_with_label(link.url, _('Open'))
                        link_btn.set_valign(Gtk.Align.CENTER)
                        row.add_suffix(link_btn)
                        link_list.append(row)

                    self.detail_blocks.append(link_list)

    def _add_fix_controls(self, inner, card, block):
        key = block.runnable_step.display_command
        button = Gtk.Button(label=_('Fix'), valign=Gtk.Align.CENTER)
        button.connect('clicked', lambda _button: self._submit_fix(block))
        inner.append(button)
        spinner = Gtk.Spinner()
        inner.append(spinner)
        status = Gtk.Label(xalign=0.0, wrap=True, selectable=True)
        status.set_margin_start(14)
        status.set_margin_end(14)
        status.set_margin_bottom(8)
        card.append(status)
        progress = Gtk.ProgressBar()
        card.append(progress)
        self._fix_widgets.setdefault(key, []).append((button, spinner, status, progress))
        self._update_fix(key)

    def _update_fix(self, key):
        task = self._fix_tasks.get(key)
        active = task is not None and task.is_active
        for button, spinner, status, progress in self._fix_widgets.get(key, ()):
            button.set_sensitive(self._task_manager is not None and not active)
            spinner.set_spinning(active)
            spinner.set_visible(active)
            progress.set_visible(active)
            progress.set_fraction(task.progress if task is not None else 0.0)
            text = (task.error_detail or task.status_text) if task is not None else ''
            status.set_label(text)
            status.set_visible(bool(text))
            if task is not None and task.error_detail:
                status.add_css_class('error')
            else:
                status.remove_css_class('error')

    def _submit_fix(self, block):
        # Recheck the parser's rule at the action boundary, including multi-step blocks.
        if not block.is_runnable or self._task_manager is None:
            return
        step = block.runnable_step
        key = step.display_command
        previous = self._fix_tasks.get(key)
        if previous is not None and previous.is_active:
            return
        task = self._task_manager.submit_command(step.arguments, title=key)
        task.operation = key
        self._fix_tasks[key] = task
        changed = task.connect('notify', lambda *_args: self._update_fix(key))

        def finished(task, success):
            task.disconnect(changed)
            task.disconnect(done)
            self._update_fix(key)
            if success:
                if self._busy:
                    self._refresh_pending = True
                else:
                    self.refresh(force=True)

        done = task.connect('finished', finished)
        self._update_fix(key)

    def _render_detail(self, issue):
        if issue is None:
            if self._report and not self._report.issues:
                self.detail_placeholder.set_label(_('Your system is ready to brew.\nNo problems found.'))
            elif self._report and self._report.issues:
                self.detail_placeholder.set_label(_('Select an issue to see its details'))
            else:
                self.detail_placeholder.set_label(_('Ready to check'))
            self.detail_placeholder.set_visible(True)
            self.detail_content.set_visible(False)
            self._clear_detail_blocks()
            return

        self.detail_placeholder.set_visible(False)
        self.detail_content.set_visible(True)
        self.detail_title.set_label(issue.title)
        severities = {
            'warning': _('Warning'),
            'error': _('Error'),
            'unsupported': _('Unsupported configuration'),
        }
        self.detail_severity.set_label(severities.get(issue.severity, issue.severity))
        self.detail_severity.remove_css_class('font-badge')
        self.detail_severity.remove_css_class('error')
        self.detail_severity.remove_css_class('warning')
        self.detail_severity.remove_css_class('doctor-badge-warning')
        self.detail_severity.remove_css_class('doctor-badge-error')
        if issue.severity == 'warning':
            self.detail_severity.add_css_class('doctor-badge-warning')
        else:
            self.detail_severity.add_css_class('doctor-badge-error')

        self.detail_body.set_label(issue.body)
        self._clear_detail_blocks()
        if issue.blocks:
            self.detail_body.set_visible(False)
            self._render_blocks(issue.blocks)
        else:
            self.detail_body.set_visible(True)

    def _copy_output(self, _button):
        if self._report is not None:
            self._copy_text(self._report.raw_output)

    def _show_config(self, _button):
        from .command_dialog import show_command
        show_command(self.get_root(), _('Homebrew Configuration'),
                     _('Includes platform and sandbox diagnostics, including Landlock when available. '
                       'Review local paths and account details before sharing.'), args=('config',))
