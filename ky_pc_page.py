"""The KySettings PC tab: live CPU, effective memory (RAM + zram + swap) and network,
drawn in the style of Ubuntu's System Monitor resources view."""
import colorsys
import math

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio, Gdk
import json
import os
import pathlib
import threading

import ky_stats as stats

PC_CSS = b"""
.pc-hero { background-image: linear-gradient(135deg, rgba(90,102,121,0.55), rgba(37,45,59,0.95)); border-radius: 18px; }
.pc-kicker { font-size: 11px; font-weight: 800; letter-spacing: 3px; color: #A7B5C8; }
.pc-hero-free { font-size: 17px; font-weight: 700; }
.pc-hero-value { font-size: 46px; font-weight: 900; letter-spacing: -1px; color: #FFFEFB; }
"""
_css_loaded = False


def load_css():
    global _css_loaded
    if _css_loaded:
        return
    provider = Gtk.CssProvider(); provider.load_from_data(PC_CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    _css_loaded = True


def helper_path(name="ky-memory"):
    here = pathlib.Path(os.path.realpath(__file__)).parent
    for candidate in (here / "scripts" / name, here / name):
        if candidate.exists():
            return str(candidate)
    return str(pathlib.Path.home() / ".local/bin" / name)


LEVEL_TEXT = {"auto": ("Automatic (recommended)", "The card speeds up and slows down on its own"),
              "low": ("Quiet", "Holds the lowest clocks. Cooler and quieter; games run slower"),
              "high": ("Full speed", "Holds top clocks all the time. Snappier, but warmer and uses more power when idle")}
PROFILE_TEXT = {"BOOTUP_DEFAULT": "The card decides for itself (recommended)",
                "3D_FULL_SCREEN": "Ramps up fast and stays up for full-screen games",
                "POWER_SAVING": "Keeps clocks down to save power and heat",
                "VIDEO": "Smooth video playback at low power",
                "VR": "Steady clocks for VR headsets",
                "COMPUTE": "Steady clocks for AI models and number crunching"}


def eagerness_text(n):
    if n <= 40:
        return "Keeps programs in RAM and swaps only when RAM is nearly full"
    if n <= 80:
        return "Balanced: swaps idle memory once RAM gets busy"
    if n <= 120:
        return "Compresses idle memory early for the most free RAM (recommended with zram)"
    return "Squeezes hard: the most free RAM, a bit more compression work"


# Palette pulled from the KySettings mountain theme.
GRID = (0.65, 0.71, 0.78, 0.16)
AXIS = (1.0, 0.99, 0.97, 0.55)
RAM_C = (0.87, 0.36, 0.36)        # red, like System Monitor's memory line
SWAP_C = (0.36, 0.80, 0.55)       # green, like its swap line
ZRAM_C = (0.89, 0.76, 0.56)       # warm sand
EFF_C = (0.65, 0.71, 0.78)        # accent slate
RX_C = (0.38, 0.62, 0.92)
TX_C = (0.93, 0.47, 0.36)
CACHE_C = (0.48, 0.55, 0.64)
FREE_C = (0.30, 0.35, 0.44)
FAST_C = (0.56, 0.66, 0.86)        # full-speed RAM zone
DISK_C = (0.36, 0.80, 0.55)
GPU_C = (0.66, 0.55, 0.95)         # GPU usage
VRAM_C = (0.95, 0.67, 0.30)        # video memory
POWER_C = (0.40, 0.80, 0.82)       # power draw


def core_colors(n):
    return [colorsys.hsv_to_rgb(i / max(1, n), 0.55, 0.95) for i in range(n)]


class Graph(Gtk.DrawingArea):
    """A scrolling one-minute line graph with a right-hand scale, like System Monitor."""

    def __init__(self, height=150, percent=True, fill_first=False):
        super().__init__()
        self.set_content_height(height); self.set_hexpand(True)
        self.series = []          # (values, rgb, width)
        self.percent = percent
        self.fill_first = fill_first
        self.set_draw_func(self._draw)

    def set_series(self, series):
        self.series = series; self.queue_draw()

    def _scale_max(self):
        if self.percent:
            return 100.0
        peak = max((max(x for x in v if x is not None) for v, _, _ in self.series if any(x is not None for x in v)), default=0)
        top = 1024.0
        while top < peak:
            top *= 2
        return top

    def _draw(self, area, cr, w, h):
        left, right, top, bottom = 4, 62, 6, 18
        gw, gh = max(1, w - left - right), max(1, h - top - bottom)
        cr.set_source_rgba(0.05, 0.07, 0.11, 0.55)
        cr.rectangle(left, top, gw, gh); cr.fill()
        ymax = self._scale_max()
        cr.set_line_width(1)
        cr.select_font_face("Sans"); cr.set_font_size(10)
        for i in range(5):
            y = top + gh * i / 4 + 0.5
            cr.set_source_rgba(*GRID); cr.move_to(left, y); cr.line_to(left + gw, y); cr.stroke()
            value = ymax * (1 - i / 4)
            label = f"{value:.0f} %" if self.percent else stats.rate(value)
            cr.set_source_rgba(*AXIS); cr.move_to(left + gw + 6, y + 4); cr.show_text(label)
        for i in range(7):
            x = left + gw * i / 6 + 0.5
            cr.set_source_rgba(*GRID); cr.move_to(x, top); cr.line_to(x, top + gh); cr.stroke()
        for i, label in enumerate(("60 secs", "50", "40", "30", "20", "10", "")):
            if label:
                cr.set_source_rgba(*AXIS); cr.move_to(left + gw * i / 6 + 2, top + gh + 13); cr.show_text(label)
        for index, (values, rgb, width) in enumerate(self.series):
            n = len(values)
            pts = [(left + gw * k / (n - 1), top + gh * (1 - min(ymax, max(0, v)) / ymax)) for k, v in enumerate(values) if v is not None]
            if len(pts) < 2:
                continue
            cr.set_source_rgb(*rgb); cr.set_line_width(width); cr.set_line_join(1)
            cr.move_to(*pts[0])
            for p in pts[1:]:
                cr.line_to(*p)
            if index == 0 and self.fill_first:
                cr.stroke_preserve()
                cr.line_to(pts[-1][0], top + gh); cr.line_to(pts[0][0], top + gh); cr.close_path()
                cr.set_source_rgba(*rgb, 0.18); cr.fill()
            else:
                cr.stroke()


class MemoryBar(Gtk.DrawingArea):
    """One bar for the whole effective ceiling: programs, cache, free RAM, zram, disk swap."""

    def __init__(self):
        super().__init__()
        self.set_content_height(34); self.set_hexpand(True)
        self.parts = []
        self.set_draw_func(self._draw)

    def set_parts(self, parts):
        self.parts = parts; self.queue_draw()

    def _draw(self, area, cr, w, h):
        total = sum(v for v, _ in self.parts) or 1
        x, r = 0.0, 7
        cr.new_sub_path()
        cr.arc(r, r, r, math.pi, 1.5 * math.pi); cr.arc(w - r, r, r, 1.5 * math.pi, 0)
        cr.arc(w - r, h - r, r, 0, 0.5 * math.pi); cr.arc(r, h - r, r, 0.5 * math.pi, math.pi)
        cr.close_path(); cr.clip()
        for value, rgb in self.parts:
            width = w * value / total
            cr.set_source_rgb(*rgb); cr.rectangle(x, 0, width + 0.5, h); cr.fill()
            x += width


class ZoneBar(Gtk.DrawingArea):
    """The effective-RAM ceiling as three speed zones, each filled as far as it is used."""

    def __init__(self):
        super().__init__()
        self.set_content_height(18); self.set_hexpand(True)
        self.zones = []          # (capacity, used, rgb)
        self.set_draw_func(self._draw)

    def set_zones(self, zones):
        self.zones = zones; self.queue_draw()

    def _draw(self, area, cr, w, h):
        total = sum(c for c, _, _ in self.zones) or 1
        r = 6
        cr.new_sub_path()
        cr.arc(r, r, r, math.pi, 1.5 * math.pi); cr.arc(w - r, r, r, 1.5 * math.pi, 0)
        cr.arc(w - r, h - r, r, 0, 0.5 * math.pi); cr.arc(r, h - r, r, 0.5 * math.pi, math.pi)
        cr.close_path(); cr.clip()
        x = 0.0
        for capacity, used, rgb in self.zones:
            width = w * capacity / total
            cr.set_source_rgba(*rgb, 0.22); cr.rectangle(x, 0, width, h); cr.fill()
            fill = width * min(1.0, used / capacity) if capacity else 0
            cr.set_source_rgb(*rgb); cr.rectangle(x, 0, fill, h); cr.fill()
            cr.set_source_rgba(0.05, 0.07, 0.11, 0.9); cr.rectangle(x + width - 1, 0, 2, h); cr.fill()
            x += width


def swatch(rgb):
    area = Gtk.DrawingArea(); area.set_content_width(14); area.set_content_height(14)
    area.set_valign(Gtk.Align.CENTER)
    area.set_draw_func(lambda a, cr, w, h: (cr.set_source_rgb(*rgb), cr.arc(w / 2, h / 2, 6, 0, 2 * math.pi), cr.fill()))
    return area


def value_row(title, subtitle="", rgb=None):
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    if rgb:
        row.add_prefix(swatch(rgb))
    label = Gtk.Label(xalign=1); label.add_css_class("numeric")
    row.add_suffix(label)
    return row, label


class PCPage:
    def __init__(self, stack):
        self.stack = stack
        self.sampler = stats.Sampler()
        # Two columns: everything about RAM on the left (the star); GPU, then CPU and network on the right.
        self.page = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        clamp = Adw.Clamp(maximum_size=1500, tightening_threshold=1200)
        columns = Gtk.Box(spacing=28, homogeneous=True)
        columns.set_margin_top(24); columns.set_margin_bottom(24); columns.set_margin_start(24); columns.set_margin_end(24)
        self.left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        columns.append(self.left); columns.append(self.right)
        clamp.set_child(columns); self.page.set_child(clamp)
        self.column = self.left
        load_css()
        self.status = None
        self._loading = False
        self._build()
        self.refresh_status()
        # First sample after a full second, so the first CPU reading isn't a blip.
        self.timer = GLib.timeout_add_seconds(1, self._tick)

    def _group(self, title, description=""):
        g = Adw.PreferencesGroup(title=title, description=description)
        self.column.append(g); return g

    def _build(self):
        g = self._group("")
        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hero.add_css_class("card"); hero.add_css_class("pc-hero")
        for side in ("top", "bottom", "start", "end"):
            getattr(hero, f"set_margin_{side}")(0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        inner.set_margin_top(14); inner.set_margin_bottom(14); inner.set_margin_start(18); inner.set_margin_end(18)
        kicker = Gtk.Label(label="EFFECTIVE RAM", xalign=0); kicker.add_css_class("pc-kicker")
        top = Gtk.Box(spacing=14)
        self.hero_value = Gtk.Label(xalign=0); self.hero_value.add_css_class("pc-hero-value")
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, spacing=2)
        self.hero_free = Gtk.Label(xalign=0); self.hero_free.add_css_class("pc-hero-free")
        self.hero_mult = Gtk.Label(xalign=0); self.hero_mult.add_css_class("dim-label")
        side.append(self.hero_free); side.append(self.hero_mult)
        top.append(self.hero_value); top.append(side)
        self.zones = ZoneBar()
        self.zone_caption = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=14, row_spacing=2)
        self.zone_labels = []
        for rgb, name in ((FAST_C, "Full speed RAM"), (ZRAM_C, "Compressed RAM"), (DISK_C, "SSD swap")):
            box = Gtk.Box(spacing=6); box.append(swatch(rgb)); label = Gtk.Label(xalign=0)
            box.append(label); self.zone_caption.append(box); self.zone_labels.append((name, label))
        self.hero_note = Gtk.Label(xalign=0, wrap=True); self.hero_note.add_css_class("dim-label")
        for w in (kicker, top, self.zones, self.zone_caption, self.hero_note):
            inner.append(w)
        hero.append(inner); g.add(hero)
        self._build_tune()

        g = self._group("Where Your Memory Is", "Everything the PC is holding right now")
        self.bar = MemoryBar(); g.add(self.bar)
        g = self._group("")
        self.rows = {}
        for key, title, sub, rgb in (
                ("programs", "Programs in RAM", "Memory apps are actively holding", RAM_C),
                ("cache", "File cache", "Recently read files; given up instantly when apps need room", CACHE_C),
                ("free_ram", "Free RAM", "Empty right now", FREE_C),
                ("zram", "Compressed RAM (zram)", "Idle memory squeezed in place on the RAM sticks", ZRAM_C),
                ("disk", "Swap on SSD", "Overflow on disk; slowest", DISK_C),
                ("left", "Still available", "Room left before the ceiling", EFF_C)):
            row, label = value_row(title, sub, rgb); self.rows[key] = label; g.add(row)

        g = self._group("Memory and Swap History")
        self.mem_graph = Graph(height=140, fill_first=False); g.add(self.mem_graph)
        legend = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2, column_spacing=14, row_spacing=2); legend.set_margin_top(6)
        self.mem_legend = {}
        for key, name, rgb in (("ram", "RAM", RAM_C), ("zram", "zram", ZRAM_C), ("swap", "All swap", SWAP_C), ("effective", "Effective", EFF_C)):
            box = Gtk.Box(spacing=6); box.append(swatch(rgb))
            label = Gtk.Label(xalign=0); box.append(label); legend.append(box); self.mem_legend[key] = (name, label)
        g.add(legend)

        g = self._group("Compressed RAM (zram)")
        self.zram_rows = {}
        for key, title, sub in (("stored", "Stored", "Memory placed in zram"),
                                ("uses", "Real RAM it uses", "What that takes on the sticks"),
                                ("ratio", "Compression", ""),
                                ("saved", "RAM saved", "Stored minus real RAM used"),
                                ("size", "Size", "")):
            row, label = value_row(title, sub); self.zram_rows[key] = (row, label); g.add(row)

        self.swap_group = self._group("Swap Areas", "Used in priority order, highest first")
        self.swap_rows = {}

        self.column = self.right
        if self.sampler.gpu_dev:
            self._build_gpu()
        g = self._group("CPU History")
        self.cpu_graph = Graph(height=230); g.add(self.cpu_graph)
        n = len(self.sampler.cpu) - 1
        self.core_colors = core_colors(n)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2)
        flow.set_margin_top(6); flow.set_column_spacing(12); flow.set_row_spacing(4)
        self.core_labels = []
        for i in range(n):
            box = Gtk.Box(spacing=6); box.append(swatch(self.core_colors[i]))
            label = Gtk.Label(xalign=0); label.add_css_class("numeric"); box.append(label)
            flow.append(box); self.core_labels.append(label)
        g.add(flow)
        g = self._group("")
        self.cpu_rows = {}
        for key, title, sub in (("total", "Total", "All 16 threads together"), ("temp", "Temperature", "CPU package"),
                                ("load", "Load average", "1, 5 and 15 minutes")):
            row, label = value_row(title, sub); self.cpu_rows[key] = label; g.add(row)

        g = self._group("Network History")
        self.net_graph = Graph(percent=False, fill_first=True); g.add(self.net_graph)
        g = self._group("")
        self.net_rows = {}
        for key, title, rgb in (("rx", "Receiving", RX_C), ("tx", "Sending", TX_C)):
            row, label = value_row(title, "", rgb); self.net_rows[key] = (row, label); g.add(row)


    # ------------------------------------------------------------ GPU
    def _build_gpu(self):
        self.gpu_group = self._group("GPU History")
        self.gpu_graph = Graph(height=170); self.gpu_group.add(self.gpu_graph)
        legend = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3, column_spacing=14, row_spacing=2); legend.set_margin_top(6)
        self.gpu_legend = {}
        for key, name, rgb in (("busy", "Usage", GPU_C), ("vram", "Video memory", VRAM_C), ("power", "Power", POWER_C)):
            box = Gtk.Box(spacing=6); box.append(swatch(rgb))
            label = Gtk.Label(xalign=0); box.append(label); legend.append(box); self.gpu_legend[key] = (name, label)
        self.gpu_group.add(legend)
        g = self._group("")
        self.gpu_rows = {}
        for key, title, sub in (("temp", "Temperature", ""), ("fan", "Fan", ""), ("clocks", "Clocks", "Core and memory"),
                                ("spill", "Spilled into system RAM", "Video memory that didn't fit on the card. Slower, but it keeps things running"),
                                ("link", "Connection", "PCIe link to the motherboard")):
            row, label = value_row(title, sub); self.gpu_rows[key] = (row, label); g.add(row)

        self.vram_group = self._group("Video Memory by App",
                                      "What each program holds on the card. When the card fills up, the overflow moves to system RAM: things slow down, but keep running.")
        self.vram_warning = Adw.ActionRow(title="Video memory is nearly full",
                                          subtitle="Expect stutter. Closing a game or AI model frees it up.")
        self.vram_warning.add_css_class("error"); self.vram_warning.set_visible(False); self.vram_group.add(self.vram_warning)
        self.vram_rows = []
        self._apps_busy = False; self._apps_due = 0

        g = self._group("Tune GPU", "Settings the driver manages itself. Heat protection always stays on, and there is no overclocking. "
                                    "Asks for your password; nothing changes until you press Apply.")
        self.level_row = Adw.ComboRow(title="Performance")
        self.level_row.set_model(Gtk.StringList.new([LEVEL_TEXT[k][0] for k in ("auto", "low", "high")]))
        self.level_row.connect("notify::selected", self._gpu_changed); g.add(self.level_row)
        self.profile_row = Adw.ComboRow(title="Workload")
        self.profile_row.connect("notify::selected", self._gpu_changed); g.add(self.profile_row)
        self.cap_row = Adw.SpinRow.new_with_range(1, 1000, 1)
        self.cap_row.set_title("Power limit (watts)")
        self.cap_row.connect("notify::value", self._gpu_changed); g.add(self.cap_row)
        self.gpu_result = Adw.ActionRow(title="", subtitle="")
        self.gpu_reset = Gtk.Button(label="Restore defaults", valign=Gtk.Align.CENTER)
        self.gpu_reset.connect("clicked", lambda *_: self._gpu_run(["recommended"]))
        self.gpu_apply = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        self.gpu_apply.add_css_class("suggested-action"); self.gpu_apply.connect("clicked", self._gpu_apply_clicked)
        self.gpu_result.add_suffix(self.gpu_reset); self.gpu_result.add_suffix(self.gpu_apply); g.add(self.gpu_result)
        self.gpu_status = None; self._gpu_loading = False
        self.gpu_refresh()

    def gpu_refresh(self):
        try:
            proc = Gio.Subprocess.new(["/usr/bin/python3", helper_path("ky-gpu"), "status"],
                                      Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
            proc.communicate_utf8_async(None, None, self._gpu_status_done)
        except GLib.Error as exc:
            self.gpu_result.set_subtitle(f"Could not read GPU settings: {exc.message}")

    def _gpu_status_done(self, proc, result):
        try:
            _, out, _ = proc.communicate_utf8_finish(result)
            st = json.loads(out)
        except Exception as exc:
            self.gpu_result.set_subtitle(f"Could not read GPU settings: {exc}"); return
        if "error" in st:
            self.gpu_result.set_subtitle(st["error"]); self.gpu_apply.set_sensitive(False); self.gpu_reset.set_sensitive(False); return
        self.gpu_status = st; self._gpu_loading = True
        try:
            self.gpu_group.set_description(st["name"])
            self.level_row.set_selected(self._index(st["levels"], st["level"]) if st["level"] in st["levels"] else 0)
            self.gpu_profiles = st["profiles"]
            self.profile_row.set_model(Gtk.StringList.new([p["label"] for p in self.gpu_profiles]))
            self.profile_row.set_selected(self._index([p["name"] for p in self.gpu_profiles], st["profile"]))
            has_cap = st["power_min"] is not None and st["power_max"] is not None
            self.cap_row.set_visible(has_cap)
            if has_cap:
                self.cap_row.set_range(st["power_min"], st["power_max"])
                self.cap_row.set_value(round(st["power_cap"]))
        finally:
            self._gpu_loading = False
        self._gpu_changed()

    def _gpu_choice(self):
        st = self.gpu_status
        return {"level": st["levels"][self.level_row.get_selected()],
                "profile": self.gpu_profiles[self.profile_row.get_selected()]["name"] if self.gpu_profiles else st["profile"],
                "power_cap": int(self.cap_row.get_value()) if self.cap_row.get_visible() else None}

    def _gpu_current(self):
        st = self.gpu_status
        return {"level": st["level"], "profile": st["profile"],
                "power_cap": round(st["power_cap"]) if st["power_cap"] is not None and self.cap_row.get_visible() else None}

    def _gpu_changed(self, *_):
        if self._gpu_loading or not self.gpu_status:
            return
        st = self.gpu_status; choice = self._gpu_choice()
        self.level_row.set_subtitle(LEVEL_TEXT[choice["level"]][1])
        self.profile_row.set_subtitle(PROFILE_TEXT.get(choice["profile"], ""))
        if self.cap_row.get_visible():
            self.cap_row.set_subtitle(f"The driver allows {st['power_min']:.0f} to {st['power_max']:.0f} W. Lower runs cooler and quieter")
        pending = choice != self._gpu_current()
        default = {"level": "auto", "profile": "BOOTUP_DEFAULT",
                   "power_cap": round(st["power_default"]) if st["power_default"] and self.cap_row.get_visible() else None}
        self.gpu_apply.set_sensitive(pending)
        self.gpu_reset.set_sensitive(self._gpu_current() != default)
        self.gpu_result.set_subtitle("Not applied yet" if pending else
                                     "Kept after restart" if st["saved"] else "Driver defaults")

    def _gpu_apply_clicked(self, *_):
        choice, current = self._gpu_choice(), self._gpu_current()
        args = ["apply"]
        for key, flag in (("level", "--level"), ("profile", "--profile"), ("power_cap", "--power-cap")):
            if choice[key] != current[key] and choice[key] is not None:
                args += [flag, str(choice[key])]
        self._gpu_run(args)

    def _gpu_run(self, args):
        self.gpu_apply.set_sensitive(False); self.gpu_reset.set_sensitive(False)
        self.gpu_result.set_subtitle("Working… a password prompt may appear")
        try:
            proc = Gio.Subprocess.new(["/usr/bin/python3", helper_path("ky-gpu"), *args],
                                      Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
            proc.communicate_utf8_async(None, None, self._gpu_run_done)
        except GLib.Error as exc:
            self.gpu_result.set_subtitle(exc.message)

    def _gpu_run_done(self, proc, result):
        try:
            _, out, err = proc.communicate_utf8_finish(result)
        except GLib.Error as exc:
            out, err = "", exc.message
        status = proc.get_exit_status() if proc.get_if_exited() else 1
        message = None
        if status in (126, 127):
            message = "Cancelled. Nothing was changed."
        elif status != 0:
            message = (err or out or "Something went wrong.").strip().splitlines()[-1]
            dialog = Adw.MessageDialog(transient_for=self.page.get_root(), heading="Not changed" if status == 3 else "Change failed", body=message)
            dialog.add_response("ok", "OK"); dialog.present()
        else:
            message = (out or "Done.").strip().splitlines()[-1]
        self.gpu_refresh()
        GLib.timeout_add(400, lambda: (self.gpu_result.set_subtitle(message), False)[1])

    def _scan_apps(self):
        def work():
            try:
                apps = stats.read_gpu_apps()
            except Exception:
                apps = None
            GLib.idle_add(self._apps_done, apps)
        self._apps_busy = True
        threading.Thread(target=work, daemon=True).start()

    def _apps_done(self, apps):
        self._apps_busy = False
        if apps is None:
            return False
        g = self.sampler.latest.get("gpu") or {}
        used = g.get("vram_used") or 0
        shown = [a for a in apps if a[2] >= 64 * 1024 * 1024][:6]
        rest = max(0, used - sum(a[2] for a in shown))
        entries = [(name, f"Process {pid}", vram) for pid, name, vram in shown]
        if rest >= 128 * 1024 * 1024:     # apps share some buffers, so the sum can exceed the total
            entries.append(("Everything else", "Smaller apps, the desktop and the driver", rest))
        while len(self.vram_rows) < len(entries):
            row, label = value_row("", "")
            bar = Gtk.LevelBar(); bar.set_size_request(140, -1); bar.set_valign(Gtk.Align.CENTER)
            row.add_suffix(bar); self.vram_group.add(row); self.vram_rows.append((row, label, bar))
        total = g.get("vram_total") or 1
        for i, (row, label, bar) in enumerate(self.vram_rows):
            if i >= len(entries):
                row.set_visible(False); continue
            name, sub, vram = entries[i]
            row.set_visible(True); row.set_title(GLib.markup_escape_text(name)); row.set_subtitle(sub)
            label.set_label(stats.gb(vram, 2)); bar.set_value(min(1.0, vram / total))
        return False

    def _tick_gpu(self, g):
        n = self.sampler.gpu
        self.gpu_graph.set_series([(n["busy"], GPU_C, 2), (n["vram"], VRAM_C, 2), (n["power"], POWER_C, 1.5)])
        vt = g["vram_total"] or 0
        values = {"busy": f"{g['busy']:.0f} %" if g["busy"] is not None else "n/a",
                  "vram": f"{stats.gb(g['vram_used'])} of {stats.gb(vt)}" if vt else "n/a",
                  "power": f"{g['power']:.0f} of {g['power_cap']:.0f} W" if g["power"] is not None and g["power_cap"] else "n/a"}
        for key, (name, label) in self.gpu_legend.items():
            label.set_label(f"{name}  {values[key]}")
        t = g["temps"]
        parts = [f"{t[k]:.0f} °C {k}" for k in ("edge", "junction", "mem") if t.get(k) is not None]
        self.gpu_rows["temp"][1].set_label("  ".join(parts).replace("junction", "hotspot") or "n/a")
        if g.get("temp_limit"):
            self.gpu_rows["temp"][0].set_subtitle(f"The card slows itself down before the hotspot reaches {g['temp_limit']:.0f} °C")
        if g["fan"] is not None:
            pct = f" ({100 * g['fan'] / g['fan_max']:.0f} %)" if g["fan_max"] else ""
            self.gpu_rows["fan"][1].set_label(f"{g['fan']:.0f} RPM{pct}")
            self.gpu_rows["fan"][0].set_subtitle("Automatic, controlled by the card")
        self.gpu_rows["clocks"][1].set_label(" / ".join(f"{c:.0f} MHz" for c in (g["core_clock"], g["mem_clock"]) if c is not None) or "n/a")
        self.gpu_rows["spill"][1].set_label(f"{stats.gb(g['gtt_used'])} of {stats.gb(g['gtt_total'], 0)}" if g["gtt_total"] else "n/a")
        self.gpu_rows["link"][1].set_label(f"{g['link'][0]} x{g['link'][1]}" if g.get("link") else "n/a")
        self.vram_warning.set_visible(bool(vt) and g["vram_used"] / vt >= 0.92)
        self._apps_due -= 1
        if self._apps_due <= 0 and not self._apps_busy:
            self._apps_due = 3
            self._scan_apps()

    # ------------------------------------------------------------ tuning controls
    def _build_tune(self):
        g = self._group("Tune", "Every change is checked for safety first and asks for your password. Nothing changes until you press Apply.")
        self.eager_row = Adw.SpinRow.new_with_range(10, 180, 10)
        self.eager_row.set_title("Swap eagerness (swappiness)")
        self.eager_row.connect("notify::value", self._changed)
        g.add(self.eager_row)
        self.zram_row = Adw.ComboRow(title="Compressed RAM size (zram)")
        self.zram_row.connect("notify::selected", self._changed); g.add(self.zram_row)
        self.algo_row = Adw.ComboRow(title="Compression")
        self.algo_row.set_model(Gtk.StringList.new(["zstd: squeezes the most", "lz4: fastest", "lzo-rle: light"]))
        self.algo_row.connect("notify::selected", self._changed); g.add(self.algo_row)
        self.file_row = Adw.ComboRow(title="SSD swap file")
        self.file_row.connect("notify::selected", self._changed); g.add(self.file_row)
        self.preview_row = Adw.ActionRow(title="After applying")
        self.preview_label = Gtk.Label(xalign=1); self.preview_label.add_css_class("title-4")
        self.preview_row.add_suffix(self.preview_label); g.add(self.preview_row)
        actions = Adw.ActionRow(title="", subtitle="")
        self.result_row = actions
        self.reset_button = Gtk.Button(label="Restore recommended", valign=Gtk.Align.CENTER)
        self.reset_button.connect("clicked", self._recommended)
        self.apply_button = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER)
        self.apply_button.add_css_class("suggested-action"); self.apply_button.connect("clicked", self._apply)
        actions.add_suffix(self.reset_button); actions.add_suffix(self.apply_button)
        g.add(actions)
        self.install_row = Adw.ActionRow(title="Compressed RAM needs zram-tools",
                                         subtitle="A small Ubuntu package. Installing asks for your password.")
        button = Gtk.Button(label="Install", valign=Gtk.Align.CENTER); button.connect("clicked", self._install_zram)
        self.install_row.add_suffix(button); self.install_row.set_visible(False); g.add(self.install_row)

        g = self._group("Quick Actions")
        row = Adw.ActionRow(title="Free up file cache",
                            subtitle="Drops cached copies of files to show more free RAM right away. Safe; it refills as files are read again.")
        b = Gtk.Button(label="Free up", valign=Gtk.Align.CENTER); b.connect("clicked", lambda *_: self._run(["free-cache"]))
        row.add_suffix(b); g.add(row)
        self.reclaim_row = Adw.ActionRow(title="Move SSD swap back into RAM")
        self.reclaim_button = Gtk.Button(label="Move back", valign=Gtk.Align.CENTER)
        self.reclaim_button.connect("clicked", lambda *_: self._run(["reclaim"]))
        self.reclaim_row.add_suffix(self.reclaim_button); g.add(self.reclaim_row)

    def refresh_status(self):
        try:
            proc = Gio.Subprocess.new(["/usr/bin/python3", helper_path(), "status"],
                                      Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
            proc.communicate_utf8_async(None, None, self._status_done)
        except GLib.Error as exc:
            self.result_row.set_subtitle(f"Could not read memory settings: {exc.message}")

    def _status_done(self, proc, result):
        try:
            _, out, _ = proc.communicate_utf8_finish(result)
            self.status = json.loads(out)
        except Exception as exc:
            self.result_row.set_subtitle(f"Could not read memory settings: {exc}")
            return
        st = self.status; self._loading = True
        try:
            self.eager_row.set_value(st["swappiness"])
            self.zram_sizes = st["zram_sizes"]
            self.zram_row.set_model(Gtk.StringList.new(["Off" if v == 0 else f"{v} GB" for v in self.zram_sizes]))
            self.zram_row.set_selected(self._index(self.zram_sizes, st["zram_size"]))
            self.algo_row.set_selected(self._index(st["algos"], st["zram_algo"]))
            current_file = round(st["swapfile"]["size"] / stats.GB) if st["swapfile"]["active"] else 0
            sizes = sorted(set(st["swapfile_sizes"]) | {current_file})
            self.file_sizes = sizes
            self.file_row.set_model(Gtk.StringList.new(["None" if v == 0 else f"{v} GB" for v in sizes]))
            self.file_row.set_selected(self._index(sizes, current_file))
            installed = st["zram_installed"]
            for row in (self.zram_row, self.algo_row):
                row.set_sensitive(installed)
            self.install_row.set_visible(not installed)
            self.file_row.set_sensitive(st["swapfile"]["supported"])
            sf = st["swapfile"]
            self.file_row.set_subtitle(f"{sf['path']} · {sf['disk_free'] / stats.GB:.0f} GB free on that drive, 50 GB always kept free"
                                       if sf["supported"] else f"Needs an ext4 drive (this one is {sf['fstype']})")
        finally:
            self._loading = False
        self._changed()

    @staticmethod
    def _index(options, value):
        try:
            return options.index(value)
        except ValueError:
            return 0

    def _choice(self):
        st = self.status
        return {"swappiness": int(self.eager_row.get_value()),
                "zram_size": self.zram_sizes[self.zram_row.get_selected()],
                "zram_algo": st["algos"][self.algo_row.get_selected()],
                "swapfile": self.file_sizes[self.file_row.get_selected()]}

    def _current(self):
        st = self.status
        return {"swappiness": st["swappiness"], "zram_size": st["zram_size"], "zram_algo": st["zram_algo"],
                "swapfile": round(st["swapfile"]["size"] / stats.GB) if st["swapfile"]["active"] else 0}

    def _ceiling(self, choice):
        st = self.status; e = st["effective"]
        ratio = e["zram_ratio"] if choice["zram_algo"] == st["zram_algo"] else (3.0 if choice["zram_algo"] == "zstd" else 2.2)
        file_now = st["swapfile"]["size"] if st["swapfile"]["active"] else 0
        other_disk = e["disk_total"] - file_now
        return e["ram_total"] + choice["zram_size"] * stats.GB * (1 - 1 / ratio) + other_disk + choice["swapfile"] * stats.GB

    def _changed(self, *args):
        if self._loading or not self.status:
            return
        choice, current = self._choice(), self._current()
        self.eager_row.set_subtitle(eagerness_text(choice["swappiness"]))
        z = choice["zram_size"]
        ratio = 3.0 if choice["zram_algo"] == "zstd" else 2.2
        self.zram_row.set_subtitle("Off" if z == 0 else
                                   f"Adds about {z * (1 - 1 / ratio):.0f} GB; uses up to {z / ratio:.0f} GB of real RAM when full")
        new, now = self._ceiling(choice) / stats.GB, self._ceiling(current) / stats.GB
        delta = new - now
        self.preview_label.set_label(f"{new:.0f} GB effective" + (f" ({delta:+.0f} GB)" if abs(delta) >= 0.5 else ""))
        pending = choice != current
        self.apply_button.set_sensitive(pending)
        self.reset_button.set_sensitive(choice != {"swappiness": 100, "zram_size": 16, "zram_algo": "zstd", "swapfile": 48}
                                        and self.status["zram_installed"])
        self.preview_row.set_subtitle("No changes yet" if not pending else
                                      "Grows swap before shrinking anything, and refuses if data would not fit")

    def _recommended(self, *_):
        r = self.status["recommended"]
        self.eager_row.set_value(r["swappiness"])
        self.zram_row.set_selected(self._index(self.zram_sizes, r["zram_size"]))
        self.algo_row.set_selected(self._index(self.status["algos"], r["zram_algo"]))
        if r["swapfile"] in self.file_sizes:
            self.file_row.set_selected(self.file_sizes.index(r["swapfile"]))
        self._changed()

    def _apply(self, *_):
        choice, current = self._choice(), self._current()
        args = ["apply"]
        if choice["swappiness"] != current["swappiness"]:
            args += ["--swappiness", str(choice["swappiness"])]
        if (choice["zram_size"], choice["zram_algo"]) != (current["zram_size"], current["zram_algo"]):
            args += ["--zram-size", str(choice["zram_size"]), "--zram-algo", choice["zram_algo"]]
        if choice["swapfile"] != current["swapfile"]:
            args += ["--swapfile", str(choice["swapfile"])]
        self._run(args)

    def _install_zram(self, *_):
        self._run(None, ["pkexec", "apt", "install", "-y", "zram-tools"])

    def _run(self, args, argv=None):
        argv = argv or ["/usr/bin/python3", helper_path(), *args]
        self.apply_button.set_sensitive(False); self.reclaim_button.set_sensitive(False)
        self.result_row.set_subtitle("Working… a password prompt may appear")
        try:
            proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
            proc.communicate_utf8_async(None, None, self._run_done)
        except GLib.Error as exc:
            self.result_row.set_subtitle(exc.message)

    def _run_done(self, proc, result):
        try:
            _, out, err = proc.communicate_utf8_finish(result)
        except GLib.Error as exc:
            out, err = "", exc.message
        status = proc.get_exit_status() if proc.get_if_exited() else 1
        if status == 0:
            self.result_row.set_subtitle((out or "Done.").strip().splitlines()[-1])
        elif status in (126, 127):
            self.result_row.set_subtitle("Cancelled. Nothing was changed.")
        else:
            message = (err or out or "Something went wrong.").strip().splitlines()[-1]
            self.result_row.set_subtitle(message)
            dialog = Adw.MessageDialog(transient_for=self.page.get_root(), heading="Not changed" if status == 3 else "Change failed",
                                       body=message)
            dialog.add_response("ok", "OK"); dialog.present()
        self.refresh_status()

    def _visible(self):
        return self.stack.get_visible_child() is self.page and self.page.get_mapped()

    def _tick(self):
        try:
            d = self.sampler.sample()
        except Exception:
            return True
        if not self._visible():
            return True          # keep the history, skip the drawing
        e = d["effective"]
        ceiling = e["ceiling"] / stats.GB
        self.hero_value.set_label(f"{ceiling:.0f} GB")
        self.hero_free.set_label(f"{stats.gb(e['free'])} free right now")
        ratio = f"{e['zram_ratio']:.1f} to 1" + ("" if e["zram_ratio_live"] else " expected")
        mult = e["ceiling"] / e["ram_total"] if e["ram_total"] else 1
        self.hero_mult.set_label(f"{e['ram_total'] / stats.GB:.0f} GB of physical RAM, working like {mult:.1f}x that")
        in_ram = max(0, e["ram_used"])
        self.zones.set_zones([(e["ram_total"], in_ram, FAST_C), (e["zram_net"], e["zram_data"] - e["zram_ram"], ZRAM_C),
                              (e["disk_total"], e["disk_used"], DISK_C)])
        caps = (e["ram_total"], e["zram_net"], e["disk_total"])
        for (name, label), cap in zip(self.zone_labels, caps):
            label.set_label(f"{name}  {'+' if label is not self.zone_labels[0][1] else ''}{cap / stats.GB:.0f} GB")
        self.hero_note.set_label(f"Programs see one big pool. The first {e['ram_total'] / stats.GB:.0f} GB runs at full speed, "
                                 f"compressed RAM ({ratio}) is a little slower, SSD swap is much slower.")
        free_ram = max(0, e["ram_available"] - e["cache"])
        left = max(0, e["free"] - e["ram_available"])
        self.bar.set_parts([(e["programs"], RAM_C), (e["cache"], CACHE_C), (free_ram, FREE_C),
                            (e["zram_data"], ZRAM_C), (e["disk_used"], DISK_C), (left, (0.13, 0.16, 0.22))])
        self.rows["programs"].set_label(stats.gb(e["programs"]))
        self.rows["cache"].set_label(stats.gb(e["cache"]))
        self.rows["free_ram"].set_label(stats.gb(free_ram))
        self.rows["zram"].set_label(f"{stats.gb(e['zram_data'])} in {stats.gb(e['zram_ram'])}")
        self.rows["disk"].set_label(f"{stats.gb(e['disk_used'])} of {stats.gb(e['disk_total'], 0)}")
        self.rows["left"].set_label(stats.gb(e["free"]))
        if self.status is not None:
            need = e["disk_used"]
            fits = need and need + 3 * stats.GB <= e["ram_available"]
            self.reclaim_button.set_sensitive(bool(fits))
            self.reclaim_row.set_subtitle(
                "Nothing is on SSD swap right now" if not need else
                f"{stats.gb(need)} is on the SSD; brings it back for full speed" if fits else
                f"{stats.gb(need)} is on the SSD, but there isn't enough free RAM to bring it back yet")
        m = self.sampler.mem
        self.mem_graph.set_series([(m["ram"], RAM_C, 2), (m["zram"], ZRAM_C, 2), (m["swap"], SWAP_C, 2), (m["effective"], EFF_C, 1.5)])
        values = {"ram": f"{stats.gb(e['ram_used'])} of {stats.gb(e['ram_total'])}",
                  "zram": f"{stats.gb(e['zram_data'])} of {stats.gb(e['zram_size'], 0)}",
                  "swap": f"{stats.gb(e['swap_used'])} of {stats.gb(e['swap_total'], 0)}",
                  "effective": f"{stats.gb(e['used'])} of {e['ceiling'] / stats.GB:.0f} GB"}
        for key, (name, label) in self.mem_legend.items():
            label.set_label(f"{name}  {values[key]}")
        z = self.zram_rows
        z["stored"][1].set_label(stats.gb(e["zram_data"], 2))
        z["uses"][1].set_label(stats.gb(e["zram_ram"], 2))
        z["ratio"][1].set_label(ratio)
        z["ratio"][0].set_subtitle("Live from what zram holds now" if e["zram_ratio_live"] else "zstd usually manages about 3 to 1; shown live once zram holds data")
        z["saved"][1].set_label(stats.gb(e["zram_saved"], 2))
        algos = ", ".join(sorted({x["algorithm"] for x in d["zram"]})) or "off"
        z["size"][1].set_label(f"{stats.gb(e['zram_size'], 0)} ({algos})")
        seen = set()
        for s in sorted(d["swaps"], key=lambda s: -s["priority"]):
            seen.add(s["name"])
            if s["name"] not in self.swap_rows:
                kind = "Compressed RAM" if s["name"].startswith("/dev/zram") else ("Swap file" if s["kind"] == "file" else "Swap partition")
                row, label = value_row(s["name"], kind)
                bar = Gtk.LevelBar(); bar.set_size_request(140, -1); bar.set_valign(Gtk.Align.CENTER)
                row.add_suffix(bar); self.swap_group.add(row); self.swap_rows[s["name"]] = (row, label, bar)
            row, label, bar = self.swap_rows[s["name"]]
            label.set_label(f"{stats.gb(s['used'])} of {stats.gb(s['size'], 0)} · priority {s['priority']}")
            bar.set_value(s["used"] / s["size"] if s["size"] else 0)
        for name in list(self.swap_rows):
            if name not in seen:
                self.swap_group.remove(self.swap_rows.pop(name)[0])
        cores = self.sampler.cpu[1:]
        self.cpu_graph.set_series([(cores[i], self.core_colors[i], 1.3) for i in range(len(cores))]
                                  + [(self.sampler.cpu[0], (1, 1, 1), 2.2)])
        for i, label in enumerate(self.core_labels):
            label.set_label(f"CPU{i + 1}  {d['cpu'][i + 1]:.0f} %")
        self.cpu_rows["total"].set_label(f"{d['cpu'][0]:.0f} %")
        self.cpu_rows["temp"].set_label(f"{d['temp']:.0f} °C" if d["temp"] is not None else "n/a")
        self.cpu_rows["load"].set_label("  ".join(f"{x:.2f}" for x in d["load"]))
        if d.get("gpu") and self.sampler.gpu_dev:
            self._tick_gpu(d["gpu"])
        n = self.sampler.net
        self.net_graph.set_series([(n["rx"], RX_C, 2), (n["tx"], TX_C, 2)])
        self.net_rows["rx"][1].set_label(stats.rate(d["rx"]))
        self.net_rows["rx"][0].set_subtitle(f"Total since boot {stats.gb(d['rx_total'])}")
        self.net_rows["tx"][1].set_label(stats.rate(d["tx"]))
        self.net_rows["tx"][0].set_subtitle(f"Total since boot {stats.gb(d['tx_total'])}")
        return True
