"""The KySettings PC tab: live CPU, effective memory (RAM + zram + swap) and network,
drawn in the style of Ubuntu's System Monitor resources view."""
import colorsys
import math

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib

import ky_stats as stats

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
DISK_C = (0.36, 0.80, 0.55)


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
        self.page = Adw.PreferencesPage(); self.page.set_title("PC")
        self.page.set_icon_name("computer-symbolic")
        self._build()
        # First sample after a full second, so the first CPU reading isn't a blip.
        self.timer = GLib.timeout_add_seconds(1, self._tick)

    def _group(self, title, description=""):
        g = Adw.PreferencesGroup(title=title, description=description)
        self.page.add(g); return g

    def _build(self):
        g = self._group("Effective Memory", "Everything this PC can hold: RAM, then compressed RAM (zram), then swap on the SSD")
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        head.set_margin_top(4); head.set_margin_bottom(8)
        self.headline = Gtk.Label(xalign=0); self.headline.add_css_class("title-1")
        self.subline = Gtk.Label(xalign=0, wrap=True); self.subline.add_css_class("dim-label")
        self.bar = MemoryBar()
        head.append(self.headline); head.append(self.subline); head.append(self.bar)
        g.add(head)
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
        self.mem_graph = Graph(fill_first=False); g.add(self.mem_graph)
        legend = Gtk.Box(spacing=18); legend.set_margin_top(6)
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

        g = self._group("CPU History")
        self.cpu_graph = Graph(height=170); g.add(self.cpu_graph)
        n = len(self.sampler.cpu) - 1
        self.core_colors = core_colors(n)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8, min_children_per_line=4)
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
        self.headline.set_label(f"{stats.gb(e['free'])} free of about {e['ceiling'] / stats.GB:.0f} GB")
        ratio = f"{e['zram_ratio']:.1f} to 1" + ("" if e["zram_ratio_live"] else " (expected)")
        self.subline.set_label(
            f"{stats.gb(e['ram_total'], 0)} usable RAM, {stats.gb(e['zram_size'], 0)} zram at {ratio}, "
            f"{stats.gb(e['disk_total'], 0)} swap on SSD. Full speed up to about {e['ram_total'] / stats.GB:.0f} GB, "
            "a little slower in zram, much slower on the SSD.")
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
        n = self.sampler.net
        self.net_graph.set_series([(n["rx"], RX_C, 2), (n["tx"], TX_C, 2)])
        self.net_rows["rx"][1].set_label(stats.rate(d["rx"]))
        self.net_rows["rx"][0].set_subtitle(f"Total since boot {stats.gb(d['rx_total'])}")
        self.net_rows["tx"][1].set_label(stats.rate(d["tx"]))
        self.net_rows["tx"][0].set_subtitle(f"Total since boot {stats.gb(d['tx_total'])}")
        return True
