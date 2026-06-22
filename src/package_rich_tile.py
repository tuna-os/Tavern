from gi.repository import Gtk, GObject, Adw

@Gtk.Template(resource_path='/org.tunaos.tavern/package-rich-tile.ui')
class TavernRichPackageTile(Gtk.Box):
    __gtype_name__ = 'TavernRichPackageTile'

    __gsignals__ = {
        'clicked': (GObject.SignalFlags.RUN_LAST, None, ()),
        'install-requested': (GObject.SignalFlags.RUN_FIRST, None, (object,)),
    }

    package_icon = Gtk.Template.Child()
    name_label = Gtk.Template.Child()
    short_desc = Gtk.Template.Child()
    type_badge = Gtk.Template.Child()
    install_button = Gtk.Template.Child()
    cover_box = Gtk.Template.Child()

    def __init__(self, package, **kwargs):
        super().__init__(**kwargs)
        self.package = package
        
        # Click gesture for the whole tile
        self._gesture = Gtk.GestureClick.new()
        self._gesture.connect('released', self._on_gesture_released)
        self.add_controller(self._gesture)
        
        self.name_label.set_text(package.name)
        
        # Display short desc (or type as fallback)
        desc = package.description if package.description else (
            "GUI Application" if package.pkg_type == 'cask' else "Command Line Utility"
        )
        self.short_desc.set_text(desc)
        
        if package.pkg_type == 'cask':
            self.type_badge.set_text("cask")
            self.type_badge.add_css_class("cask-badge")
            # For aesthetics, let's vary the color of the cover slightly
            self.cover_box.add_css_class("cask-cover")
        else:
            self.type_badge.set_text("formula")
            self.type_badge.remove_css_class("cask-badge")
            self.cover_box.add_css_class("formula-cover")
            
        self._update_state()

        # Connect signals
        self.install_button.connect('clicked', self._on_install_clicked)

    def _update_state(self):
        if self.package.installed:
            self.install_button.set_label("Open")
            self.install_button.set_visible(self.package.pkg_type == 'cask')
            # Make the button visually distinct when installed
            self.install_button.remove_css_class("suggested-action")
        else:
            self.install_button.set_label("Get")
            self.install_button.set_visible(True)
            self.install_button.add_css_class("suggested-action")

    def _on_install_clicked(self, button):
        if not self.package.installed:
            self.emit('install-requested', self.package)
        else:
            # For 'Open', we let the main tile handle it, so we just emit clicked
            self.emit('clicked')

    def _on_gesture_released(self, gesture, n_press, x, y):
        # Emit 'clicked' for the navigation logic in pages
        self.emit('clicked')

    def update_package_state(self):
        self._update_state()
