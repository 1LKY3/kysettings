#!/usr/bin/python3
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('terminal', str(Path(__file__).with_name('ky-terminal')))
spec = importlib.util.spec_from_loader(loader.name, loader)
t = importlib.util.module_from_spec(spec)
loader.exec_module(t)


class Restoration(unittest.TestCase):
    def test_restores_manual_choice_and_diversion(self):
        calls = []
        def run(*args):
            calls.append(args)
            return '/example.so.kysettings-disabled' if '--truename' in args else ''
        with tempfile.TemporaryDirectory() as d, patch.object(t, 'run', run), patch.object(t, 'EXTENSION', Path(d)/'extension.py'):
            t.EXTENSION.write_text('test')
            t.restore_system({'extensions': ['/example.so'], 'alternative': {'Status': 'manual', 'Value': '/usr/bin/old-terminal'}})
            self.assertFalse(t.EXTENSION.exists())
        self.assertIn(('/usr/bin/update-alternatives', '--set', 'x-terminal-emulator', '/usr/bin/old-terminal'), calls)
        self.assertTrue(any('--remove' in c for c in calls))

    def test_restores_auto_without_pin(self):
        with patch.object(t, 'run') as run, patch.object(t, 'EXTENSION'):
            t.restore_system({'extensions': [], 'alternative': {'Status': 'auto', 'Value': '/old'}})
            run.assert_called_once_with('/usr/bin/update-alternatives', '--auto', 'x-terminal-emulator')

    def test_failure_retains_system_snapshot(self):
        with tempfile.TemporaryDirectory() as d, patch.object(t.os, 'geteuid', return_value=0), patch.object(t, 'SYSTEM', Path(d)/'before.json'), patch.object(t, 'restore_system', side_effect=RuntimeError('failure')):
            t.save(t.SYSTEM, {'extensions': [], 'alternative': {}})
            with self.assertRaises(RuntimeError):
                t.system('disable')
            self.assertTrue(t.SYSTEM.exists())

    def test_auth_failure_does_not_write_settings(self):
        with tempfile.TemporaryDirectory() as d, patch.object(t, 'USER', Path(d)/'before.json'), patch.object(t, 'settings') as settings, patch.object(t, 'run', side_effect=RuntimeError('cancelled')):
            settings.return_value.get_user_value.return_value = None
            with self.assertRaises(RuntimeError):
                t.user('enable')
            settings.return_value.set_string.assert_not_called()
            self.assertTrue(t.USER.exists())


if __name__ == '__main__':
    unittest.main()
