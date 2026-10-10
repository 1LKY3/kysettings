"""ky-gpu: profile parsing, safety checks and the baked boot script, on fake sysfs data."""
import importlib.machinery, importlib.util, os, sys, tempfile, unittest
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
import ky_stats as stats
loader = importlib.machinery.SourceFileLoader("ky_gpu", os.path.join(here, "ky-gpu"))
spec = importlib.util.spec_from_loader("ky_gpu", loader); g = importlib.util.module_from_spec(spec); loader.exec_module(g)

NAVI = """PROFILE_INDEX(NAME) CLOCK_TYPE(NAME) FPS MinFreqType
 0 BOOTUP_DEFAULT*:
                    0(       GFXCLK)       0       5       1       0
 1 3D_FULL_SCREEN :
                    0(       GFXCLK)       0       5       1       0
 2   POWER_SAVING :
 5        COMPUTE :
 6         CUSTOM :
"""
OLDER = """NUM        MODE_NAME     SCLK_UP_HYST
  0   BOOTUP_DEFAULT:        -
  1   3D_FULL_SCREEN*:        0
  4          COMPUTE:        0
"""


def status(**kw):
    st = {"profiles": [{"index": 0, "name": "BOOTUP_DEFAULT", "label": "Default", "active": True},
                       {"index": 5, "name": "COMPUTE", "label": "Compute (AI models)", "active": False}],
          "power_min": 182.0, "power_max": 194.0}
    st.update(kw); return st


class Profiles(unittest.TestCase):
    def test_navi_layout(self):
        p = g.parse_profiles(NAVI)
        self.assertEqual([n for _, n, _ in p], ["BOOTUP_DEFAULT", "3D_FULL_SCREEN", "POWER_SAVING", "COMPUTE", "CUSTOM"])
        self.assertEqual([n for _, n, a in p if a], ["BOOTUP_DEFAULT"])

    def test_older_layout_star_after_name(self):
        p = g.parse_profiles(OLDER)
        self.assertEqual([(i, n) for i, n, a in p if a], [(1, "3D_FULL_SCREEN")])


class Safety(unittest.TestCase):
    def test_rejects_levels_outside_the_safe_list(self):
        for bad in ("manual", "profile_peak", "high;reboot"):
            with self.assertRaises(g.Unsafe):
                g.plan_from(["--level", bad], status())

    def test_power_cap_must_stay_inside_driver_range(self):
        self.assertEqual(g.plan_from(["--power-cap", "185"], status())["power_cap"], 185)
        for bad in ("181", "195", "300"):
            with self.assertRaises(g.Unsafe):
                g.plan_from(["--power-cap", bad], status())

    def test_unknown_profile_and_option(self):
        with self.assertRaises(g.Unsafe):
            g.plan_from(["--profile", "CUSTOM"], status())
        with self.assertRaises(g.Unsafe):
            g.plan_from(["--fan", "100"], status())

    def test_boot_script_has_only_baked_values(self):
        text = g.boot_script("0000:2d:00.0", "high", 5, 185)
        self.assertIn("echo high >", text); self.assertIn("echo 5 >", text); self.assertIn("echo 185000000 >", text)
        self.assertNotIn("/home", text)


class Readers(unittest.TestCase):
    def test_read_gpu_from_fake_sysfs(self):
        with tempfile.TemporaryDirectory() as d:
            hw = os.path.join(d, "hwmon", "hwmon3"); os.makedirs(hw)
            files = {f"{d}/gpu_busy_percent": "42", f"{d}/mem_info_vram_used": str(6 * stats.GB),
                     f"{d}/mem_info_vram_total": str(12 * stats.GB), f"{hw}/power1_average": "120000000",
                     f"{hw}/power1_cap": "194000000", f"{hw}/temp2_label": "junction", f"{hw}/temp2_input": "71000"}
            for path, value in files.items():
                open(path, "w").write(value + "\n")
            r = stats.read_gpu({"device": d, "hwmon": hw, "pci": "x"})
            self.assertEqual(r["busy"], 42); self.assertEqual(r["vram_used"], 6 * stats.GB)
            self.assertEqual(r["power"], 120); self.assertEqual(r["temps"], {"junction": 71})
            self.assertIsNone(r["fan"])


if __name__ == "__main__":
    unittest.main()
