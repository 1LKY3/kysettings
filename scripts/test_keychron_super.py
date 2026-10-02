"""Regression checks for persistence, restoration, and failed updates."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('keychron_super', str(Path(__file__).with_name('keychron-super')))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class RemapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.rule = self.root / 'rule.hwdb'
        for name, value in [('RULE', self.rule), ('INPUT', self.root / 'input')]:
            self.enterContext(patch.object(helper, name, value))
        self.rebuild = self.enterContext(patch.object(helper, 'rebuild'))

    def test_adopts_existing_fix(self):
        self.rule.write_text('# Original standalone fix\n' + helper.BODY)
        self.assertTrue(helper.enabled())

    def test_enable_disable_without_keyboard(self):
        helper.apply(True)
        self.assertTrue(helper.enabled())
        helper.apply(False)
        self.assertFalse(self.rule.exists())

    def test_custom_rule_untouched(self):
        self.rule.write_text('custom mapping\n')
        with self.assertRaises(RuntimeError):
            helper.apply(True)
        self.assertEqual(self.rule.read_text(), 'custom mapping\n')
        self.rebuild.assert_not_called()

    def test_database_failure_restores_enabled_rule(self):
        self.rule.write_text(helper.BODY)
        self.rebuild.side_effect = [RuntimeError('database failure'), None]
        with self.assertRaisesRegex(RuntimeError, 'database failure'):
            helper.apply(False)
        self.assertTrue(helper.enabled())

    def test_database_failure_restores_absence(self):
        self.rebuild.side_effect = [RuntimeError('database failure'), None]
        with self.assertRaises(RuntimeError):
            helper.apply(True)
        self.assertFalse(self.rule.exists())

    def test_immediate_restore_and_live_failure_rollback(self):
        device = helper.INPUT / 'event9' / 'device'
        device.mkdir(parents=True)
        (device / 'modalias').write_text('input:b0003v05ACp024Fe0111-test')
        original_open = helper.os.open
        def open_device(path, *args, **kwargs):
            return 999 if path == '/dev/input/event9' else original_open(path, *args, **kwargs)
        original_close = helper.os.close
        def close_device(fd):
            if fd != 999:
                original_close(fd)
        with patch.object(helper.os, 'open', side_effect=open_device), \
             patch.object(helper.os, 'close', side_effect=close_device), \
             patch.object(helper, 'keycode', return_value=126), \
             patch.object(helper, 'set_keycode') as change:
            self.rule.write_text(helper.BODY)
            helper.apply(False)
            change.assert_called_once_with(999, 125)
            self.rule.write_text(helper.BODY)
            change.reset_mock()
            change.side_effect = [RuntimeError('device failure'), None]
            with self.assertRaisesRegex(RuntimeError, 'device failure'):
                helper.apply(False)
            self.assertTrue(helper.enabled())
            self.assertEqual(change.call_args_list[-1].args, (999, 126))


if __name__ == '__main__':
    unittest.main()
