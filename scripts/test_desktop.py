"""Preset lifecycle checks with isolated settings and no desktop/service changes."""
import os
os.environ['GSETTINGS_BACKEND'] = 'memory'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import json
import tempfile
import unittest
from unittest.mock import patch
import ky_desktop as d


class PresetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.values = {'a': False, 'b': True}
        self.enterContext(patch.object(d, 'run', return_value='State: ACTIVE'))

    def feature(self, key, target=True):
        return d.Feature(key, lambda: self.values[key],
                         lambda: self.values.__setitem__(key, target),
                         lambda old: self.values.__setitem__(key, old),
                         lambda: self.values[key] == target)

    def preset(self, items=None):
        return d.Preset(items if items is not None else [self.feature('a'), self.feature('b', False)],
                        self.root/'snapshot.json', self.root/'state.json')

    def test_theme_or_matching_values_does_not_imply_applied(self):
        self.values = {'a': True, 'b': False}
        self.assertEqual(self.preset().status()['status'], 'Not applied')

    def test_apply_customization_reapply_restore(self):
        p = self.preset()
        self.assertEqual(p.apply(), [])
        baseline = p.snapshot.read_bytes()
        self.assertEqual(p.status()['status'], 'Applied')
        self.values['a'] = False
        self.assertEqual(p.status()['status'], 'Customized')
        self.assertEqual(p.apply(), [])
        self.assertEqual(p.snapshot.read_bytes(), baseline)
        self.assertEqual(p.restore(), [])
        self.assertEqual(self.values, {'a': False, 'b': True})
        self.assertFalse(p.snapshot.exists())
        self.assertFalse(p.state.exists())

    def test_already_enabled_feature_stays_enabled_after_restore(self):
        p = self.preset([self.feature('b')])
        p.apply()
        self.values['b'] = False
        p.restore()
        self.assertTrue(self.values['b'])

    def test_failed_apply_and_failed_restore_keep_recovery_data(self):
        item = self.feature('a')
        item.apply = lambda: (_ for _ in ()).throw(RuntimeError('authentication cancelled'))
        p = self.preset([item])
        self.assertTrue(p.apply())
        self.assertEqual(p.status()['status'], 'Incomplete')
        item.restore = lambda old: (_ for _ in ()).throw(RuntimeError('restore denied'))
        self.assertTrue(p.restore())
        self.assertTrue(p.snapshot.exists())
        self.assertEqual(p.status()['status'], 'Incomplete')

    def test_new_features_do_not_replace_existing_baseline(self):
        p = self.preset([self.feature('a')])
        p.apply()
        p.items.append(self.feature('b', False))
        p.apply()
        self.assertEqual(json.loads(p.snapshot.read_text())['entries'], {'a': False, 'b': True})

    def test_invalid_snapshot_prevents_all_mutation(self):
        p = self.preset()
        p.snapshot.write_text('{"version": 99}')
        with self.assertRaises(RuntimeError):
            p.apply()
        self.assertEqual(self.values, {'a': False, 'b': True})
        self.assertFalse(p.state.exists())

    def test_unavailable_capture_is_not_applied(self):
        item = self.feature('a')
        item.capture = lambda: (_ for _ in ()).throw(RuntimeError('missing schema'))
        p = self.preset([item])
        self.assertTrue(p.apply())
        self.assertFalse(self.values['a'])
        self.assertNotIn('a', json.loads(p.snapshot.read_text())['entries'])

    def test_inherited_and_explicit_gsettings_restore_exactly(self):
        schema = 'org.gnome.desktop.interface'
        d.settings(schema).reset('gtk-theme')
        d.put(schema, 'font-name', 'Custom 15')
        p = self.preset([d.setting_feature(schema, 'gtk-theme', 'Yaru-sage-dark'),
                         d.setting_feature(schema, 'font-name', 'Ubuntu Sans 11')])
        p.apply()
        self.assertIsNone(json.loads(p.snapshot.read_text())['entries'][schema+'/gtk-theme'])
        p.restore()
        self.assertIsNone(d.capture_key(schema, 'gtk-theme'))
        self.assertEqual(d.get(schema, 'font-name'), 'Custom 15')

    def test_legacy_snapshot_keeps_old_values_when_extended(self):
        schema = 'org.gnome.desktop.interface'
        p = self.preset([d.setting_feature(schema, 'font-name', 'Ubuntu Sans 11')])
        p.snapshot.write_text(json.dumps({'version': 1, 'settings': [
            {'schema': schema, 'key': 'font-name', 'user_set': True, 'type': 's', 'value': 'Original 14'}],
            'dash_minimize_enabled': False}))
        p.apply()
        self.assertEqual(json.loads(p.snapshot.read_text())['entries'][schema+'/font-name'], "'Original 14'")

    def test_date_shortcut_is_idempotent_and_preserves_other_shortcuts(self):
        settings = d.settings(d.KEYS)
        settings.reset('custom-keybindings')
        item = d.date_feature()
        original = item.capture()
        item.apply(); item.apply()
        self.assertEqual(len(d.get(d.KEYS, 'custom-keybindings')), 1)
        self.assertTrue(item.matches())
        item.restore(original)
        self.assertIsNone(d.capture_key(d.KEYS, 'custom-keybindings'))

    def test_file_snapshot_preserves_content_permissions_and_absence(self):
        path = self.root/'flag'
        self.assertIsNone(d.read_file(path))
        path.write_bytes(b'custom\x00value'); path.chmod(0o640)
        original = d.read_file(path)
        path.unlink(); d.write_file(path, original)
        self.assertEqual(d.read_file(path), original)
        d.write_file(path, None)
        self.assertFalse(path.exists())

    def test_terminal_restore_recovers_partial_enable(self):
        with patch.object(d, 'CONFIG', self.root):
            (self.root/'terminal-before.json').write_text('{}')
            item = d.terminal_feature()
            item.restore(False)
            self.assertEqual(d.run.call_args.args[-1], 'disable')


if __name__ == '__main__':
    unittest.main()
