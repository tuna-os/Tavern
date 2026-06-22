import gi
gi.require_version('GLib', '2.0')
from gi.repository import GLib

try:
    pkg_id = "test_pkg"
    meta = {
        "id": GLib.Variant("s", pkg_id),
        "name": GLib.Variant("s", "Test Pkg"),
        "description": GLib.Variant("s", "Desc")
    }
    icon_name = "org.tunaos.tavern-symbolic"
    v = GLib.Icon.new_for_string(icon_name).serialize()
    # serialize returns a variant, usually (sv) or similar.
    # What type is returned by serialize()?
    print("Icon variant type:", v.get_type_string())
    meta["icon"] = v

    metas = [meta]
    final_variant = GLib.Variant("(aa{sv})", (metas,))
    print("Success:", final_variant.print_(True))
except Exception as e:
    print("Error:", e)
