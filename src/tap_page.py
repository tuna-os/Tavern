# tap_page.py - Tap browser page with add/remove support and org avatars
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
from urllib.request import Request, urlopen

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Adw, Gtk, GObject, GLib, GdkPixbuf, Gdk
from .package_tile import TavernPackageTile
from .logging_util import get_logger

_log = get_logger('tap_page')

# ── Avatar fetch helper ──────────────────────────────────────────────────────

def _fetch_avatar_pixbuf(github_user, size=48):
    """Fetch a GitHub user/org avatar; returns a square GdkPixbuf or None."""
    url = f'https://github.com/{github_user}.png?size={size * 2}'
    try:
        req = Request(url, headers={'User-Agent': 'Tavern/0.1'})
        with urlopen(req, timeout=8) as resp:
            data = resp.read()
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        pb = loader.get_pixbuf()
        if pb:
            return pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
    except Exception as e:
        _log.debug('Avatar fetch failed for %s: %s', github_user, e)
    return None


# ── "Add Tap" dialog ─────────────────────────────────────────────────────────



# ── Page widget ──────────────────────────────────────────────────────────────

@Gtk.Template(resource_path='/dev/hanthor/Tavern/tap-page.ui')
class TavernTapPage(Adw.Bin):
    __gtype_name__ = 'TavernTapPage'

    __gsignals__ = {
        'package-activated': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'install-requested': (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'remove-requested':  (GObject.SignalFlags.RUN_LAST, None, (object,)),
        'tap-operation':     (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    tap_page_stack       = Gtk.Template.Child()
    tap_list             = Gtk.Template.Child()
    tap_content_stack    = Gtk.Template.Child()
    tap_name_label       = Gtk.Template.Child()
    tap_count_label      = Gtk.Template.Child()
    packages_flow        = Gtk.Template.Child()
    add_tap_button       = Gtk.Template.Child()
    add_tap_empty_button = Gtk.Template.Child()
    remove_tap_button    = Gtk.Template.Child()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._backend       = None
        self._tap_data      = {}  # tap_name -> [Package, ...]
        self._selected_tap  = None
        self._avatar_cache  = {}  # gh_user -> Gdk.Texture | None

        self.tap_list.connect('row-selected', self._on_tap_row_selected)
        self.add_tap_button.connect('clicked', self._on_add_tap_clicked)
        self.add_tap_empty_button.connect('clicked', self._on_add_tap_clicked)
        self.remove_tap_button.connect('clicked', self._on_remove_tap_clicked)

    def set_backend(self, backend):
        self._backend = backend
        backend.connect('taps-loaded', self._on_taps_loaded)

    # ── Backend signal ───────────────────────────────────────────────────────

    def _on_taps_loaded(self, backend, tap_packages):
        _log.info('Taps loaded: %d taps with packages', len(tap_packages))
        self._tap_data = dict(tap_packages)
        self._populate_tap_list()

    # ── Sidebar ──────────────────────────────────────────────────────────────

    def _populate_tap_list(self):
        while child := self.tap_list.get_first_child():
            self.tap_list.remove(child)

        if not self._tap_data:
            self.tap_page_stack.set_visible_child_name('no-taps')
            self.tap_content_stack.set_visible_child_name('select')
            self._selected_tap = None
            self.remove_tap_button.set_sensitive(False)
            return

        self.tap_page_stack.set_visible_child_name('content')

        prev_selected = self._selected_tap
        for tap_name in sorted(self._tap_data.keys()):
            row = self._make_tap_row(tap_name, self._tap_data[tap_name])
            self.tap_list.append(row)
            self._load_tap_avatar_async(row, tap_name)

        restored = False
        if prev_selected and prev_selected in self._tap_data:
            idx = sorted(self._tap_data.keys()).index(prev_selected)
            row = self.tap_list.get_row_at_index(idx)
            if row:
                self.tap_list.select_row(row)
                restored = True

        if not restored:
            first = self.tap_list.get_row_at_index(0)
            if first:
                self.tap_list.select_row(first)

    def _make_tap_row(self, tap_name, packages):
        n_formula = sum(1 for p in packages if p.pkg_type == 'formula')
        n_cask    = sum(1 for p in packages if p.pkg_type == 'cask')
        parts = []
        if n_formula:
            parts.append(f'{n_formula} formula{"e" if n_formula != 1 else ""}')
        if n_cask:
            parts.append(f'{n_cask} cask{"s" if n_cask != 1 else ""}')
        subtitle = ', '.join(parts) if parts else 'No packages'

        row = Adw.ActionRow()
        row.set_title(tap_name)
        row.set_subtitle(subtitle)
        row.set_activatable(False)
        row._tap_name = tap_name

        avatar = Adw.Avatar(size=36, text=tap_name, show_initials=True)
        avatar.set_valign(Gtk.Align.CENTER)
        row.add_prefix(avatar)
        row._avatar_widget = avatar
        return row

    def _load_tap_avatar_async(self, row, tap_name):
        gh_user = tap_name.split('/')[0]
        if gh_user in self._avatar_cache:
            texture = self._avatar_cache[gh_user]
            if texture:
                self._apply_avatar(row, texture)
            return

        def _thread():
            pb = _fetch_avatar_pixbuf(gh_user, size=36)
            texture = Gdk.Texture.new_for_pixbuf(pb) if pb else None
            self._avatar_cache[gh_user] = texture
            if texture:
                GLib.idle_add(self._apply_avatar, row, texture)

        threading.Thread(target=_thread, daemon=True).start()

    def _apply_avatar(self, row, texture):
        avatar = getattr(row, '_avatar_widget', None)
        if avatar:
            avatar.set_custom_image(texture)

    # ── Content area ─────────────────────────────────────────────────────────

    def _on_tap_row_selected(self, listbox, row):
        if not row:
            self._selected_tap = None
            self.remove_tap_button.set_sensitive(False)
            return
        tap_name = getattr(row, '_tap_name', None)
        if tap_name:
            self._selected_tap = tap_name
            self.remove_tap_button.set_sensitive(True)
            self._show_tap_packages(tap_name)

    def _show_tap_packages(self, tap_name):
        packages = self._tap_data.get(tap_name, [])
        _log.debug('Showing %d packages for tap: %s', len(packages), tap_name)

        self.tap_name_label.set_label(tap_name)
        n = len(packages)
        self.tap_count_label.set_label(f'{n} package{"s" if n != 1 else ""}')

        while child := self.packages_flow.get_first_child():
            self.packages_flow.remove(child)

        for pkg in packages:
            tile = TavernPackageTile(package=pkg)
            tile.connect('activated', self._on_tile_clicked)
            tile.connect('install-requested', self._on_tile_install_requested)
            tile.connect('remove-requested', self._on_tile_remove_requested)
            self._load_tile_icon(tile, pkg)
            self.packages_flow.append(tile)

        self.tap_content_stack.set_visible_child_name('packages')

    # ── Add tap ──────────────────────────────────────────────────────────────

    def _on_add_tap_clicked(self, button):
        already = set(self._tap_data.keys())

        # ── Build dialog ──────────────────────────────────────────────────────
        dialog = Adw.AlertDialog()
        dialog.set_heading('Add Homebrew Tap')
        dialog.set_body('Select a popular tap or enter one manually.')
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('add', 'Add')
        dialog.set_response_appearance('add', Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response('add')
        dialog.set_close_response('cancel')

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_size_request(360, -1)

        pop_label = Gtk.Label(label='Popular Taps', xalign=0)
        pop_label.add_css_class('heading')
        root.append(pop_label)

        scroll = Gtk.ScrolledWindow()
        scroll.props.hscrollbar_policy = Gtk.PolicyType.NEVER
        scroll.set_min_content_height(200)
        scroll.set_max_content_height(260)
        scroll.set_propagate_natural_height(True)

        # Content stack: loading → list
        content_stack = Gtk.Stack()
        content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        content_stack.set_transition_duration(200)

        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        loading_box.set_valign(Gtk.Align.CENTER)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_margin_top(24)
        loading_box.set_margin_bottom(24)
        spinner = Adw.Spinner()
        spinner.set_size_request(28, 28)
        loading_box.append(spinner)
        lbl = Gtk.Label(label='Fetching popular taps…')
        lbl.add_css_class('dim-label')
        lbl.add_css_class('caption')
        loading_box.append(lbl)
        content_stack.add_named(loading_box, 'loading')

        tap_listbox = Gtk.ListBox()
        tap_listbox.add_css_class('boxed-list')
        tap_listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        content_stack.add_named(tap_listbox, 'list')

        scroll.set_child(content_stack)
        root.append(scroll)

        sep = Gtk.Separator()
        sep.set_margin_top(4)
        root.append(sep)

        manual_label = Gtk.Label(label='Or enter a tap manually (user/repo):', xalign=0)
        manual_label.add_css_class('caption')
        manual_label.add_css_class('dim-label')
        root.append(manual_label)

        entry = Gtk.Entry()
        entry.set_placeholder_text('user/repo')
        entry.set_activates_default(True)
        root.append(entry)

        dialog.set_extra_child(root)

        # ── Populate list when taps arrive ────────────────────────────────────
        def on_taps_fetched(taps):
            if not taps:
                no_row = Adw.ActionRow()
                no_row.set_title('No results — enter a tap manually below')
                no_row.set_sensitive(False)
                tap_listbox.append(no_row)
            else:
                _iter = iter(taps)

                def _append_next():
                    try:
                        info = next(_iter)
                    except StopIteration:
                        return False
                    tap_name = info['name']
                    gh_user  = info['gh_user']
                    desc     = info.get('desc', '')

                    row = Adw.ActionRow()
                    row.set_title(tap_name)
                    row.set_subtitle(desc or tap_name)
                    row._tap_name = tap_name

                    avatar = Adw.Avatar(size=36, text=gh_user, show_initials=True)
                    avatar.set_valign(Gtk.Align.CENTER)
                    row.add_prefix(avatar)

                    if tap_name in already:
                        check = Gtk.Image(icon_name='object-select-symbolic', pixel_size=16)
                        check.add_css_class('success')
                        check.set_valign(Gtk.Align.CENTER)
                        row.add_suffix(check)
                        row.set_sensitive(False)

                    tap_listbox.append(row)

                    def _fetch_av(user=gh_user, av=avatar):
                        pb = _fetch_avatar_pixbuf(user, size=36)
                        if pb:
                            texture = Gdk.Texture.new_for_pixbuf(pb)
                            GLib.idle_add(av.set_custom_image, texture)
                    threading.Thread(target=_fetch_av, daemon=True).start()
                    return True

                GLib.idle_add(_append_next)

            content_stack.set_visible_child_name('list')

        if self._backend:
            self._backend.fetch_popular_taps_async(on_taps_fetched)
        else:
            on_taps_fetched([])

        # ── Row selection fills entry ─────────────────────────────────────────
        def on_row_selected(lb, row):
            if row and hasattr(row, '_tap_name'):
                entry.set_text(row._tap_name)

        tap_listbox.connect('row-selected', on_row_selected)

        def on_entry_changed(e):
            text = e.get_text().strip()
            sel = tap_listbox.get_selected_row()
            if sel and getattr(sel, '_tap_name', None) != text:
                tap_listbox.unselect_all()

        entry.connect('changed', on_entry_changed)

        dialog.connect('response', self._on_add_dialog_response,
                       lambda: entry.get_text().strip())
        dialog.present(self.get_root())

    def _on_add_dialog_response(self, dialog, response, get_name_fn):
        if response != 'add':
            return
        tap_name = get_name_fn()
        if not tap_name or '/' not in tap_name:
            self.emit('tap-operation', 'Invalid tap name — use user/repo format')
            return
        self._run_tap(tap_name)

    def _run_tap(self, tap_name):
        self.add_tap_button.set_sensitive(False)
        self.add_tap_empty_button.set_sensitive(False)
        self.emit('tap-operation', f'Adding tap {tap_name}…')

        def on_done(success, msg):
            self.add_tap_button.set_sensitive(True)
            self.add_tap_empty_button.set_sensitive(True)
            if success:
                self.emit('tap-operation', f'Added tap {tap_name}')
            else:
                short = msg.split('\n')[0] if msg else 'Failed'
                self.emit('tap-operation', f'Failed to add tap: {short}')

        self._backend.tap_async(tap_name, on_done)

    # ── Remove tap ───────────────────────────────────────────────────────────

    def _on_remove_tap_clicked(self, button):
        if not self._selected_tap:
            return
        tap_name = self._selected_tap
        dialog = Adw.AlertDialog()
        dialog.set_heading('Remove Tap')
        dialog.set_body(
            f'Remove tap "{tap_name}"?\n\n'
            'Packages from this tap will no longer be available to install.'
        )
        dialog.add_response('cancel', 'Cancel')
        dialog.add_response('remove', 'Remove')
        dialog.set_response_appearance('remove', Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response('cancel')
        dialog.set_close_response('cancel')
        dialog.connect('response', self._on_remove_tap_response, tap_name)
        dialog.present(self.get_root())

    def _on_remove_tap_response(self, dialog, response, tap_name):
        if response != 'remove':
            return
        self._run_untap(tap_name)

    def _run_untap(self, tap_name):
        self.remove_tap_button.set_sensitive(False)
        self.emit('tap-operation', f'Removing tap {tap_name}…')

        def on_done(success, msg):
            if success:
                self.emit('tap-operation', f'Removed tap {tap_name}')
            else:
                short = msg.split('\n')[0] if msg else 'Failed'
                self.emit('tap-operation', f'Failed to remove tap: {short}')
                self.remove_tap_button.set_sensitive(bool(self._selected_tap))

        self._backend.untap_async(tap_name, on_done)

    # ── Tile helpers ─────────────────────────────────────────────────────────

    def _load_tile_icon(self, tile, package):
        if not self._backend:
            return

        def on_icon_fetched(pkg, pixbuf):
            if pixbuf:
                tile.set_icon_pixbuf(pixbuf)

        self._backend.fetch_icon_async(package, on_icon_fetched)

    def _on_tile_clicked(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('package-activated', pkg)

    def _on_tile_install_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('install-requested', pkg)

    def _on_tile_remove_requested(self, tile):
        pkg = tile.get_package()
        if pkg:
            self.emit('remove-requested', pkg)
