#!/usr/bin/python3
import importlib.machinery
import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import gi
gi.require_version('Nautilus', '4.0')

loader = importlib.machinery.SourceFileLoader(
    'copy_path',
    str(Path(__file__).resolve().parent.parent / 'nautilus/ky-copy-path.py'))
spec = importlib.util.spec_from_loader(loader.name, loader)
c = importlib.util.module_from_spec(spec)
loader.exec_module(c)


class Info:
    def __init__(self, uri, scheme='file'):
        self.uri, self.scheme = uri, scheme

    def get_uri(self):
        return self.uri

    def get_uri_scheme(self):
        return self.scheme


class Menu(unittest.TestCase):
    def provider(self, enabled=True):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory)
        flag = Path(directory) / 'flag'
        if enabled:
            flag.touch()
        patcher = patch.object(c, 'FLAG', flag)
        patcher.start()
        self.addCleanup(patcher.stop)
        return c.KyCopyPath()

    def test_hidden_while_toggle_is_off(self):
        provider = self.provider(enabled=False)
        self.assertEqual(provider.get_file_items([Info('file:///tmp/a.txt')]), [])
        self.assertEqual(provider.get_background_items(Info('file:///tmp')), [])

    def test_single_file(self):
        items = self.provider().get_file_items([Info('file:///tmp/a.txt')])
        self.assertEqual([i.get_property('label') for i in items], ['Copy Path'])
        self.assertEqual(items[0].get_property('name'), 'KyCopyPath::copy-file')

    def test_multi_selection(self):
        items = self.provider().get_file_items(
            [Info('file:///tmp/a.txt'), Info('file:///tmp/b')])
        self.assertEqual([i.get_property('label') for i in items], ['Copy 2 Paths'])

    def test_background_folder_has_its_own_name(self):
        provider = self.provider()
        file_items = provider.get_file_items([Info('file:///tmp/a.txt')])
        folder_items = provider.get_background_items(Info('file:///tmp'))
        self.assertEqual([i.get_property('label') for i in folder_items],
                         ['Copy Path'])
        self.assertNotEqual(file_items[0].get_property('name'),
                            folder_items[0].get_property('name'))

    def test_ignores_non_local_uris(self):
        provider = self.provider()
        self.assertEqual(provider.get_file_items([Info('smb://server/share',
                                                       scheme='smb')]), [])
        self.assertEqual(provider.get_background_items(
            Info('trash:///x', scheme='trash')), [])

    def test_paths_for_rejects_empty_and_non_local(self):
        self.assertIsNone(c.paths_for([]))
        self.assertIsNone(c.paths_for([Info('trash:///x', scheme='trash')]))

    def test_copies_each_path_on_its_own_line(self):
        provider = c.KyCopyPath()
        with patch.object(c, 'copy_text') as copy:
            provider._copy(None, ['/tmp/a', '/tmp/b'])
        copy.assert_called_once_with('/tmp/a\n/tmp/b')


class Clipboard(unittest.TestCase):
    def test_prefers_wl_copy_on_wayland(self):
        with patch.dict(c.os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}), \
             patch.object(c.shutil, 'which', side_effect=lambda n: '/usr/bin/' + n):
            self.assertEqual(c.clipboard_command(), ['wl-copy'])

    def test_xclip_without_wayland(self):
        with patch.dict(c.os.environ, {}, clear=True), \
             patch.object(c.shutil, 'which',
                          side_effect=lambda n: '/usr/bin/xclip' if n == 'xclip' else None):
            self.assertEqual(c.clipboard_command(), ['xclip', '-selection', 'clipboard'])

    def test_none_when_no_tool(self):
        with patch.dict(c.os.environ, {}, clear=True), \
             patch.object(c.shutil, 'which', return_value=None):
            self.assertIsNone(c.clipboard_command())


if __name__ == '__main__':
    unittest.main()
