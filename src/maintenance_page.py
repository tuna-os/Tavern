"""On-demand security, user-service and disk-maintenance controls."""
# SPDX-License-Identifier: GPL-3.0-or-later

import gettext
import threading
from gi.repository import Adw, GLib, Gtk
from .brew_commands import parse_services, parse_vulns, run_read, transcript, version_install_args
from .command_dialog import show_command

_ = gettext.gettext


class MaintenancePage(Adw.NavigationPage):
    def __init__(self, manager, runner=run_read):
        super().__init__(title=_('Maintenance'))
        self._manager = manager
        self._runner = runner
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24,
                      margin_top=24, margin_bottom=24, margin_start=18, margin_end=18)
        scroll.set_child(Adw.Clamp(child=box, maximum_size=800))
        toolbar.set_content(scroll)
        self.set_child(toolbar)

        security = Adw.PreferencesGroup(title=_('Installed Formula Security'),
            description=_('Check OSV.dev through Homebrew. This sends package source and version '
                          'information to OSV; casks and other package managers are not scanned.'))
        self.scan_button = Gtk.Button(label=_('Scan Installed Formulae'), halign=Gtk.Align.START)
        self.scan_button.connect('clicked', self._scan)
        security.add(self.scan_button)
        self.security_status = Gtk.Label(label=_('Not scanned'), xalign=0, wrap=True, selectable=True)
        security.add(self.security_status)
        self.security_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.security_list.add_css_class('boxed-list')
        security.add(self.security_list)
        self._security_output = ''
        copy = Gtk.Button(label=_('View Scan Output'), halign=Gtk.Align.START)
        copy.connect('clicked', lambda _b: show_command(
            self.get_root(), _('Security Scan Output'),
            _('Warnings and skipped formulae are part of the report.'), text=self._security_output))
        security.add(copy)
        box.append(security)

        services = Adw.PreferencesGroup(title=_('User Services'),
            description=_('Start, stop or restart services for your user account. '
                          'System-wide services are not changed. Homebrew applies persistent '
                          'service environment overrides when starting services.'))
        self.services_button = Gtk.Button(label=_('Refresh Services'), halign=Gtk.Align.START)
        self.services_button.connect('clicked', self._load_services)
        services.add(self.services_button)
        self.services_status = Gtk.Label(label=_('Not loaded'), xalign=0, wrap=True, selectable=True)
        services.add(self.services_status)
        self.services_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.services_list.add_css_class('boxed-list')
        services.add(self.services_list)
        box.append(services)

        cleanup = Adw.PreferencesGroup(title=_('Disk Maintenance'),
            description=_('Review Homebrew’s dry-run output before deleting anything. '
                          'The final command recalculates its targets; they may change while queued. '
                          'Deleted downloads and old package versions are not moved to Trash.'))
        for command, title, description in (
            ('cleanup', _('Clean Old Versions and Downloads'),
             _('Remove stale downloads and old installed versions using Homebrew’s default retention rules.')),
            ('autoremove', _('Remove Unused Dependencies'),
             _('Uninstall formulae that Homebrew considers no longer needed as dependencies.')),
        ):
            row = Adw.ActionRow(title=title, subtitle=description, use_markup=False)
            button = Gtk.Button(label=_('Preview'), valign=Gtk.Align.CENTER)
            button.connect('clicked', lambda _b, cmd=command, label=title:
                           self._cleanup(cmd, label))
            row.add_suffix(button)
            cleanup.add(row)
        box.append(cleanup)
        versions = Adw.PreferencesGroup(title=_('Advanced: Historical Formula'),
            description=_('Homebrew 7 can extract an old formula into a personal tap. '
                          'Extracted versions receive no automatic security fixes. '
                          'Prefer a maintained versioned formula when one is available.'))
        self.formula_entry = Adw.EntryRow(title=_('Formula name'))
        self.version_entry = Adw.EntryRow(title=_('Exact version, for example 14.1.0'))
        versions.add(self.formula_entry)
        versions.add(self.version_entry)
        version_button = Gtk.Button(label=_('Review Version Install…'), halign=Gtk.Align.START)
        version_button.connect('clicked', self._version_install)
        versions.add(version_button)
        box.append(versions)

    def _version_install(self, _button):
        try:
            args = version_install_args(self.formula_entry.get_text().strip(),
                                        self.version_entry.get_text().strip())
        except ValueError as error:
            show_command(self.get_root(), _('Check Formula and Version'), str(error), text=str(error))
            return
        show_command(self.get_root(), _('Install a Historical Formula?'),
                     _('Homebrew may create a personal versions tap and extract a formula from Git history. '
                       'You must maintain extracted formulae yourself; they receive no automatic security fixes. '
                       'The build may be slow or fail. This does not pin your current installation, '
                       'and it does not support casks. There is no dry-run for this command.'),
                     text='brew ' + ' '.join(args),
                     confirm=lambda: self._manager.submit_command(args, _('Install Historical Formula')),
                     confirm_label=_('Install Historical Formula'))

    def _request(self, button, status, args, parser, complete):
        if not button.get_sensitive():
            return
        button.set_sensitive(False)
        status.set_label(_('Loading…'))

        def done(result, data, error):
            button.set_sensitive(True)
            if error is not None:
                status.set_label(_('Check failed; previous results may be stale.\n{error}').format(error=error))
            else:
                complete(result, data)
            return False

        def worker():
            try:
                result = self._runner(args)
                data = parser(result)
            except Exception as error:
                GLib.idle_add(done, None, None, str(error))
            else:
                GLib.idle_add(done, result, data, None)

        threading.Thread(target=worker, daemon=True, name='tavern-maintenance').start()

    @staticmethod
    def _clear(listbox):
        while child := listbox.get_first_child():
            listbox.remove(child)

    def _scan(self, _button):
        self._request(self.scan_button, self.security_status, ('vulns', '--json'),
                      parse_vulns, self._show_scan)

    def _show_scan(self, result, data):
        self._security_output = transcript(result)
        self._clear(self.security_list)
        count = sum(len(f['vulnerabilities']) for f in data['findings'])
        summary = _('Open vulnerabilities reported: {count}').format(count=count)
        skipped = data['skipped_formulae']
        if skipped:
            summary += '\n' + _('Skipped formulae: {names}').format(names=', '.join(skipped))
        if result.stderr or (result.returncode and not count):
            summary += '\n' + _('Coverage may be incomplete. Review the command warnings.')
            summary += '\n' + (result.stderr or '')
        summary += '\n' + _('A scan is not a guarantee that installed software is safe.')
        self.security_status.set_label(summary)
        for finding in data['findings']:
            for key, state in (('vulnerabilities', _('Open')), ('patched', _('Resolved by formula patch'))):
                for vuln in finding[key]:
                    row = Adw.ExpanderRow(
                        title=f"{finding['formula']} {finding['version']} — {vuln['id']}",
                        subtitle=f"{state} · {vuln.get('severity') or _('Unknown severity')}",
                        use_markup=False)
                    fixed = ', '.join(vuln['fixed_versions']) or _('No released fix reported')
                    detail = str(vuln.get('summary') or '') + '\n' + _('Fixed versions: {versions}').format(versions=fixed)
                    row.add_row(Gtk.Label(label=detail, xalign=0, selectable=True, wrap=True,
                                          margin_start=12, margin_end=12, margin_top=12, margin_bottom=12))
                    self.security_list.append(row)

    def _load_services(self, _button):
        self._request(self.services_button, self.services_status, ('services', 'list', '--json'),
                      parse_services, self._show_services)

    def _show_services(self, result, services):
        self._clear(self.services_list)
        self.services_status.set_label(result.stderr or (_('No user services found') if not services else ''))
        for service in services:
            row = Adw.ExpanderRow(title=service['name'], subtitle=service['status'], use_markup=False)
            buttons = Gtk.Box(spacing=8, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
            for action, label in (('start', _('Start')), ('stop', _('Stop')), ('restart', _('Restart'))):
                button = Gtk.Button(label=label, hexpand=True)
                button.connect('clicked', lambda _b, name=service['name'], op=action, text=label:
                               self._service_action(name, op, text))
                buttons.append(button)
            row.add_row(buttons)
            self.services_list.append(row)

    def _service_action(self, name, action, label):
        title = f'{label}: {name}'

        def execute():
            task = self._manager.submit_command(('services', action, name), title)
            task.connect('finished', lambda *_: self._load_services(None))

        show_command(self.get_root(), title,
                     _('This changes the service for your user account. Start registers it at login; '
                       'stop unregisters it. Restart may interrupt clients using the service.'),
                     text=f'brew services {action} {name}', confirm=execute,
                     confirm_label=label, destructive=action != 'start')

    def _cleanup(self, command, title):
        show_command(self.get_root(), title,
                     _('Review the removal list. Homebrew recalculates it when the queued task runs.'),
                     args=(command, '--dry-run'),
                     confirm=lambda: self._manager.submit_command((command,), title),
                     confirm_label=_('Remove'), destructive=True, runner=self._runner)
