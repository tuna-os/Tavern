import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio
class App(Gio.Application):
    def do_dbus_register(self, connection, object_path):
        print("Registering")
        return True
app = App(application_id='org.test', flags=Gio.ApplicationFlags.FLAGS_NONE)
app.register(None)
