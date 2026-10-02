"""Copy Path Files action; user-level, gated by a flag file.

The extension is installed with KySettings and stays inert until the
Copy Path on Right-Click toggle creates
~/.config/kysettings/copy-path.enabled. Because the flag is read every
time a menu opens, switching the toggle takes effect in already-open
Files windows.
"""
import os
from pathlib import Path
import shutil
import subprocess
from gi.repository import GObject, Gio, Nautilus

FLAG = Path.home() / ".config/kysettings/copy-path.enabled"


def paths_for(files):
    """Absolute paths for the given FileInfos, or None if any is unusable."""
    paths = []
    for info in files:
        if info is None or info.get_uri_scheme() != "file":
            return None
        path = Gio.File.new_for_uri(info.get_uri()).get_path()
        if not path:
            return None
        paths.append(path)
    return paths or None


def clipboard_command():
    """Copy command for the current session, or None for the Gdk fallback."""
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        return ["wl-copy"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard"]
    return None


def copy_text(text):
    command = clipboard_command()
    if command:
        try:
            subprocess.run(command, input=text, text=True, check=True,
                           timeout=10)
            return
        except Exception:
            pass
    from gi.repository import Gdk
    display = Gdk.Display.get_default()
    if display:
        display.get_clipboard().set(text)


class KyCopyPath(GObject.GObject, Nautilus.MenuProvider):
    def _items(self, files, name):
        if not FLAG.exists():
            return []
        paths = paths_for(files)
        if not paths:
            return []
        label = "Copy Path" if len(paths) == 1 else f"Copy {len(paths)} Paths"
        item = Nautilus.MenuItem(name=name, label=label,
                                 tip="Copy the full path to the clipboard")
        item.connect("activate", self._copy, paths)
        return [item]

    def _copy(self, _item, paths):
        copy_text("\n".join(paths))

    def get_file_items(self, files):
        return self._items(files, "KyCopyPath::copy-file")

    def get_background_items(self, current_folder):
        return (self._items([current_folder], "KyCopyPath::copy-folder")
                if current_folder else [])
