"""ky_stats: effective-memory math and /proc parsing on fixed inputs."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ky_stats as s

GB = s.GB


class Effective(unittest.TestCase):
    def mem(self, **kw):
        base = {"MemTotal": 32 * GB, "MemAvailable": 12 * GB, "MemFree": 2 * GB, "Cached": 10 * GB,
                "Buffers": 0, "SReclaimable": 0, "Shmem": 0, "Committed_AS": 70 * GB, "CommitLimit": 90 * GB}
        base.update(kw); return base

    def test_ceiling_uses_assumed_ratio_until_zram_holds_data(self):
        swaps = [{"name": "/dev/zram0", "kind": "partition", "size": 16 * GB, "used": 0, "priority": 100},
                 {"name": "/dev/nvme1n1p1", "kind": "partition", "size": 16 * GB, "used": 6 * GB, "priority": 10},
                 {"name": "/mnt/storage/swapfile", "kind": "file", "size": 48 * GB, "used": 0, "priority": 5}]
        zram = [{"name": "/dev/zram0", "disksize": 16 * GB, "data": 0, "compressed": 0, "ram": 0, "algorithm": "zstd"}]
        e = s.effective(self.mem(), swaps, zram)
        self.assertFalse(e["zram_ratio_live"])
        self.assertAlmostEqual(e["ceiling"] / GB, 32 + 64 + 16 * (1 - 1 / 3), places=3)
        self.assertEqual(e["disk_total"], 64 * GB); self.assertEqual(e["disk_used"], 6 * GB)
        self.assertEqual(e["used"], 20 * GB + 6 * GB)

    def test_live_ratio_and_zram_pages_not_counted_twice(self):
        zram = [{"name": "/dev/zram0", "disksize": 16 * GB, "data": 6 * GB, "compressed": 2 * GB, "ram": 2 * GB, "algorithm": "zstd"}]
        swaps = [{"name": "/dev/zram0", "kind": "partition", "size": 16 * GB, "used": 6 * GB, "priority": 100}]
        e = s.effective(self.mem(), swaps, zram)
        self.assertTrue(e["zram_ratio_live"]); self.assertAlmostEqual(e["zram_ratio"], 3.0)
        self.assertEqual(e["programs"], 18 * GB)          # 20 GB RAM in use minus zram's own 2 GB
        self.assertEqual(e["used"], 18 * GB + 6 * GB)     # programs + data stored in zram
        self.assertEqual(e["zram_saved"], 4 * GB)


class Parsing(unittest.TestCase):
    def test_cpu_percent(self):
        self.assertEqual(s.cpu_percent([(50, 100)], [(100, 200)]), [50.0])
        self.assertEqual(s.cpu_percent([(5, 10)], [(5, 10)]), [0.0])

    def test_swaps_and_net(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("Filename Type Size Used Priority\n/dev/zram0 partition 1024 512 100\n")
        self.assertEqual(s.read_swaps(f.name)[0]["used"], 512 * 1024)
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("h1\nh2\n    lo: 999 0 0 0 0 0 0 0 999 0 0 0 0 0 0 0\n  eth0: 100 0 0 0 0 0 0 0 40 0 0 0 0 0 0 0\nincusbr0: 7 0 0 0 0 0 0 0 7 0 0 0 0 0 0 0\n")
        self.assertEqual(s.read_net(f.name), (100, 40))

    def test_rate_and_gb(self):
        self.assertEqual(s.rate(2048), "2.0 KB/s"); self.assertEqual(s.gb(GB * 1.5), "1.5 GB")


if __name__ == "__main__":
    unittest.main()
