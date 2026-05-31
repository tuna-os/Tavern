import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='dev.hanthor.TestApp', flags=Gio.ApplicationFlags.FLAGS_NONE)
        # self.connect('dbus-register', self.on_dbus_register)
        
    def do_dbus_register(self, connection, object_path):
        print("do_dbus_register called!")
        # return True without chaining up
        return True

app = App()
app.register(None)
print("Registered:", app.get_is_registered())
print("DBus name:", app.get_application_id())
