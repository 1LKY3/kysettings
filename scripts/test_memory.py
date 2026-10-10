"""ky-memory: every change is range-checked and refused when data would not fit."""
import importlib.machinery, importlib.util, os, unittest
from unittest import mock

path = os.path.join(os.path.dirname(__file__), "ky-memory")
loader = importlib.machinery.SourceFileLoader("ky_memory", path)
spec = importlib.util.spec_from_loader("ky_memory", loader); m = importlib.util.module_from_spec(spec); loader.exec_module(m)
GB = m.GB


class Safety(unittest.TestCase):
    def test_swappiness_range_is_enforced_before_writing(self):
        with mock.patch.object(m, "SYSCTL") as f:
            for bad in (0, 5, 181, 200):
                with self.assertRaises(m.Unsafe):
                    m.set_swappiness(bad)
            f.write_text.assert_not_called()

    def test_moving_data_needs_room_plus_margin(self):
        with mock.patch.object(m, "room_outside", return_value=10 * GB):
            m.check_move(7 * GB, set(), "x")
            with self.assertRaises(m.Unsafe):
                m.check_move(9 * GB, set(), "x")

    def test_swapfile_keeps_50_gb_free_and_only_known_sizes(self):
        info = {"path": "/mnt/storage/swapfile", "size": 48 * GB, "active": True, "used": 0,
                "supported": True, "fstype": "ext4", "disk_free": 60 * GB}
        with mock.patch.object(m, "swapfile_info", return_value=info), mock.patch.object(m, "sh") as sh:
            with self.assertRaises(m.Unsafe):
                m.set_swapfile(64)          # 60 free + 48 own - 50 reserve = 58 < 64
            with self.assertRaises(m.Unsafe):
                m.set_swapfile(50)          # not an offered size
            sh.assert_not_called()

    def test_swapfile_refuses_on_other_filesystems(self):
        info = {"path": "/swapfile-ky", "size": 0, "active": False, "used": 0,
                "supported": False, "fstype": "btrfs", "disk_free": 500 * GB}
        with mock.patch.object(m, "swapfile_info", return_value=info), mock.patch.object(m, "sh") as sh:
            with self.assertRaises(m.Unsafe):
                m.set_swapfile(16)
            sh.assert_not_called()

    def test_zram_values_are_checked(self):
        with mock.patch.object(m, "zram_installed", return_value=True), mock.patch.object(m, "sh") as sh:
            with self.assertRaises(m.Unsafe):
                m.set_zram(20, "zstd")
            with self.assertRaises(m.Unsafe):
                m.set_zram(16, "gzip")
            sh.assert_not_called()

    def test_reclaim_refuses_when_ram_cannot_hold_it(self):
        swaps = [{"name": "/dev/sdb1", "kind": "partition", "size": 16 * GB, "used": 9 * GB, "priority": 10}]
        with mock.patch.object(m.stats, "read_swaps", return_value=swaps), \
             mock.patch.object(m.stats, "read_zram", return_value=[]), \
             mock.patch.object(m.stats, "read_meminfo", return_value={"MemAvailable": 10 * GB}), \
             mock.patch.object(m, "sh") as sh:
            with self.assertRaises(m.Unsafe):
                m.reclaim()
            sh.assert_not_called()

    def test_unknown_options_are_refused(self):
        with self.assertRaises(m.Unsafe):
            m.apply(["--everything", "1"])


if __name__ == "__main__":
    unittest.main()
