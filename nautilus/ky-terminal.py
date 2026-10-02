"""Files terminal action using Ubuntu's selected terminal; no resident helper."""
from pathlib import Path
import subprocess
from gi.repository import GObject, Gio, Nautilus


class KyTerminal(GObject.GObject, Nautilus.MenuProvider):
    def items(self, folder):
        if not Path('/var/lib/kysettings/terminal-before.json').exists():
            return []
        if not folder.is_directory() or folder.get_uri_scheme() != 'file':
            return []
        directory = Gio.File.new_for_uri(folder.get_uri()).get_path()
        if not directory:
            return []
        item = Nautilus.MenuItem(name='KyTerminal::open', label='Open in Terminal',
                                 tip='Open the default terminal in this folder')
        item.connect('activate', self.launch, directory)
        return [item]

    def launch(self, _item, directory):
        subprocess.Popen(['/usr/bin/x-terminal-emulator'], cwd=directory,
                         start_new_session=True)

    def get_background_items(self, current_folder):
        return self.items(current_folder)

    def get_file_items(self, files):
        return self.items(files[0]) if len(files) == 1 else []
