"""Live system numbers for the KySettings PC tab, read straight from /proc and /sys.

Everything here is cheap file reads (no subprocesses), so sampling once a second
costs nothing noticeable. `effective()` turns RAM + zram + disk swap into the
"effective memory" picture: how much the machine can hold before it runs out.
"""
import os
import pathlib
import time

KB = 1024
GB = 1024 ** 3
ASSUMED_ZRAM_RATIO = 3.0   # zstd on typical desktop memory, used until zram holds data


def read_meminfo(path="/proc/meminfo"):
    out = {}
    with open(path) as f:
        for line in f:
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                out[key] = int(parts[0]) * KB
    return out


def read_swaps(path="/proc/swaps"):
    """[{name, kind, size, used, priority}] in bytes."""
    rows = []
    with open(path) as f:
        next(f, None)
        for line in f:
            p = line.split()
            if len(p) >= 5:
                rows.append({"name": p[0], "kind": p[1], "size": int(p[2]) * KB,
                             "used": int(p[3]) * KB, "priority": int(p[4])})
    return rows


def read_zram(root="/sys/block"):
    """[{name, disksize, data, compressed, ram, algorithm}] in bytes, for each zram device."""
    devices = []
    for dev in sorted(pathlib.Path(root).glob("zram*")):
        try:
            disksize = int((dev / "disksize").read_text())
            if not disksize:
                continue
            mm = [int(x) for x in (dev / "mm_stat").read_text().split()]
            algo = (dev / "comp_algorithm").read_text()
            current = next((a.strip("[]") for a in algo.split() if a.startswith("[")), algo.split()[0])
            devices.append({"name": "/dev/" + dev.name, "disksize": disksize, "data": mm[0],
                            "compressed": mm[1], "ram": mm[2], "algorithm": current})
        except (OSError, ValueError, IndexError):
            continue
    return devices


def effective(mem, swaps, zram):
    """The effective-memory picture, all in bytes.

    ceiling: RAM + disk swap + what zram adds on top of the RAM it occupies
    (its size minus the RAM needed to hold that much at the live or assumed ratio).
    used: memory programs hold, wherever it lives (RAM outside zram's own pages,
    data stored in zram, data in disk swap). free = ceiling - used.
    """
    ram_total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", 0)
    cache = mem.get("Cached", 0) + mem.get("Buffers", 0) + mem.get("SReclaimable", 0) - mem.get("Shmem", 0)
    zram_names = {z["name"] for z in zram}
    disk = [s for s in swaps if s["name"] not in zram_names and not s["name"].startswith("/dev/zram")]
    disk_total = sum(s["size"] for s in disk)
    disk_used = sum(s["used"] for s in disk)
    z_size = sum(z["disksize"] for z in zram)
    z_data = sum(z["data"] for z in zram)
    z_comp = sum(z["compressed"] for z in zram)
    z_ram = sum(z["ram"] for z in zram)
    live = z_data / z_comp if z_comp and z_data >= 64 * 1024 * 1024 else None
    ratio = live or ASSUMED_ZRAM_RATIO
    z_net = max(0, z_size - z_size / ratio)
    ram_used = max(0, ram_total - available)          # includes zram's own pages
    programs = max(0, ram_used - z_ram)
    ceiling = ram_total + z_net + disk_total
    used = programs + z_data + disk_used
    return {
        "ram_total": ram_total, "ram_used": ram_used, "ram_available": available,
        "ram_free": mem.get("MemFree", 0), "cache": max(0, cache), "programs": programs,
        "zram_size": z_size, "zram_data": z_data, "zram_ram": z_ram, "zram_saved": max(0, z_data - z_ram),
        "zram_ratio": ratio, "zram_ratio_live": live is not None, "zram_net": z_net,
        "disk_total": disk_total, "disk_used": disk_used,
        "swap_total": sum(s["size"] for s in swaps), "swap_used": sum(s["used"] for s in swaps),
        "ceiling": ceiling, "used": used, "free": max(0, ceiling - used),
        "committed": mem.get("Committed_AS", 0), "commit_limit": mem.get("CommitLimit", 0),
    }


def read_cpu(path="/proc/stat"):
    """[(busy, total)] jiffies: overall first, then each logical CPU."""
    rows = []
    with open(path) as f:
        for line in f:
            if not line.startswith("cpu"):
                break
            v = [int(x) for x in line.split()[1:]]
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            total = sum(v[:8])
            rows.append((total - idle, total))
    return rows


def cpu_percent(prev, cur):
    out = []
    for (b0, t0), (b1, t1) in zip(prev, cur):
        dt = t1 - t0
        out.append(100.0 * (b1 - b0) / dt if dt > 0 else 0.0)
    return out


def read_net(path="/proc/net/dev"):
    """(received, sent) bytes summed over real interfaces (no loopback or virtual bridges)."""
    rx = tx = 0
    with open(path) as f:
        for line in list(f)[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            if name == "lo" or name.startswith(("veth", "incusbr", "docker", "br-", "virbr", "tailscale")):
                continue
            p = rest.split()
            rx += int(p[0]); tx += int(p[8])
    return rx, tx


def read_cpu_temp(root="/sys/class/hwmon"):
    """CPU package temperature in °C (AMD k10temp Tctl, or Intel coretemp), or None."""
    for hw in pathlib.Path(root).glob("hwmon*"):
        try:
            name = (hw / "name").read_text().strip()
        except OSError:
            continue
        if name not in ("k10temp", "coretemp", "zenpower"):
            continue
        for label in sorted(hw.glob("temp*_label")):
            try:
                text = label.read_text().strip()
                if text in ("Tctl", "Tdie", "Package id 0"):
                    return int((hw / label.name.replace("_label", "_input")).read_text()) / 1000
            except (OSError, ValueError):
                continue
        try:
            return int((hw / "temp1_input").read_text()) / 1000
        except (OSError, ValueError):
            continue
    return None


def load_average():
    try:
        return os.getloadavg()
    except OSError:
        return (0.0, 0.0, 0.0)


def gb(value, digits=1):
    return f"{value / GB:.{digits}f} GB"


def rate(bytes_per_s):
    for unit, size in (("MB/s", 1024 ** 2), ("KB/s", 1024)):
        if bytes_per_s >= size:
            return f"{bytes_per_s / size:.1f} {unit}"
    return f"{bytes_per_s:.0f} B/s"


# ---------------------------------------------------------------- GPU (amdgpu sysfs)
def find_gpu(root="/sys/class/drm"):
    """The first GPU whose driver reports load (amdgpu does): {device, hwmon} paths, or None."""
    try:
        cards = sorted(n for n in os.listdir(root) if n.startswith("card") and "-" not in n)
    except OSError:
        return None
    for name in cards:
        dev = os.path.realpath(os.path.join(root, name, "device"))
        if not os.path.exists(os.path.join(dev, "gpu_busy_percent")):
            continue
        hw = os.path.join(dev, "hwmon")
        hwmon = next((os.path.join(hw, h) for h in sorted(os.listdir(hw))), None) if os.path.isdir(hw) else None
        return {"device": dev, "hwmon": hwmon, "pci": os.path.basename(dev)}
    return None


def _num(path, scale=1.0):
    try:
        with open(path) as f:
            return int(f.read().split()[0]) / scale
    except (OSError, ValueError, IndexError):
        return None


def read_gpu(gpu):
    """Load, video memory, temperatures, power, fan and clocks for one GPU."""
    dev, hw = gpu["device"], gpu["hwmon"] or ""
    out = {"busy": _num(f"{dev}/gpu_busy_percent"), "mem_busy": _num(f"{dev}/mem_busy_percent"),
           "vram_used": _num(f"{dev}/mem_info_vram_used"), "vram_total": _num(f"{dev}/mem_info_vram_total"),
           "gtt_used": _num(f"{dev}/mem_info_gtt_used"), "gtt_total": _num(f"{dev}/mem_info_gtt_total"),
           "power": _num(f"{hw}/power1_average", 1e6) or _num(f"{hw}/power1_input", 1e6),
           "power_cap": _num(f"{hw}/power1_cap", 1e6),
           "fan": _num(f"{hw}/fan1_input"), "fan_max": _num(f"{hw}/fan1_max"),
           "core_clock": _num(f"{hw}/freq1_input", 1e6), "mem_clock": _num(f"{hw}/freq2_input", 1e6),
           "temps": {}}
    for i in range(1, 6):
        try:
            label = pathlib.Path(f"{hw}/temp{i}_label").read_text().strip()
        except OSError:
            continue
        out["temps"][label] = _num(f"{hw}/temp{i}_input", 1000)
    out["temp_limit"] = _num(f"{hw}/temp2_crit", 1000)
    try:
        out["link"] = (pathlib.Path(f"{dev}/current_link_speed").read_text().strip(),
                       pathlib.Path(f"{dev}/current_link_width").read_text().strip())
    except OSError:
        out["link"] = None
    return out


def read_gpu_apps(proc="/proc"):
    """[(pid, name, vram_bytes)] for programs holding video memory, largest first.

    Reads only file handles open on /dev/dri, deduplicated by DRM client, so a
    full pass costs well under 0.1 s. Programs owned by other users are skipped
    (their memory still counts in the total)."""
    clients = {}
    for pid in os.listdir(proc):
        if not pid.isdigit():
            continue
        try:
            fds = os.listdir(f"{proc}/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                if not os.readlink(f"{proc}/{pid}/fd/{fd}").startswith("/dev/dri/"):
                    continue
                with open(f"{proc}/{pid}/fdinfo/{fd}") as f:
                    info = f.read()
            except OSError:
                continue
            client = vram = None
            for line in info.splitlines():
                key, _, value = line.partition(":")
                if key == "drm-client-id":
                    client = value.strip()
                elif key == "drm-memory-vram":
                    vram = int(value.split()[0]) * KB
            if client is not None and vram is not None:
                clients[client] = (pid, vram)
    per_pid = {}
    for pid, vram in clients.values():
        per_pid[pid] = per_pid.get(pid, 0) + vram
    apps = []
    for pid, vram in per_pid.items():
        try:
            name = pathlib.Path(f"{proc}/{pid}/comm").read_text().strip()
        except OSError:
            continue
        apps.append((int(pid), name, vram))
    return sorted(apps, key=lambda a: -a[2])


class Sampler:
    """Keeps one minute of history for the graphs."""
    SECONDS = 60

    def __init__(self):
        self.cpu_prev = read_cpu()
        self.net_prev = (time.monotonic(), *read_net())
        n = len(self.cpu_prev)
        self.cpu = [[None] * self.SECONDS for _ in range(n)]       # [0] = overall
        self.mem = {k: [None] * self.SECONDS for k in ("ram", "swap", "zram", "effective")}
        self.net = {k: [None] * self.SECONDS for k in ("rx", "tx")}
        self.gpu_dev = find_gpu()
        self.gpu = {k: [None] * self.SECONDS for k in ("busy", "vram", "power")}
        self.latest = {}

    @staticmethod
    def _push(series, value):
        series.append(value); del series[0]

    def sample(self):
        cur = read_cpu()
        pct = cpu_percent(self.cpu_prev, cur); self.cpu_prev = cur
        for series, value in zip(self.cpu, pct):
            self._push(series, value)
        mem = read_meminfo(); swaps = read_swaps(); zram = read_zram()
        e = effective(mem, swaps, zram)
        self._push(self.mem["ram"], 100 * e["ram_used"] / e["ram_total"] if e["ram_total"] else 0)
        self._push(self.mem["swap"], 100 * e["swap_used"] / e["swap_total"] if e["swap_total"] else 0)
        self._push(self.mem["zram"], 100 * e["zram_data"] / e["zram_size"] if e["zram_size"] else 0)
        self._push(self.mem["effective"], 100 * e["used"] / e["ceiling"] if e["ceiling"] else 0)
        now = time.monotonic(); rx, tx = read_net(); t0, rx0, tx0 = self.net_prev
        dt = max(1e-3, now - t0); self.net_prev = (now, rx, tx)
        self._push(self.net["rx"], max(0, rx - rx0) / dt)
        self._push(self.net["tx"], max(0, tx - tx0) / dt)
        self.latest = {"cpu": pct, "effective": e, "swaps": swaps, "zram": zram,
                       "temp": read_cpu_temp(), "load": load_average(),
                       "rx": self.net["rx"][-1], "tx": self.net["tx"][-1], "rx_total": rx, "tx_total": tx}
        if self.gpu_dev:
            g = read_gpu(self.gpu_dev)
            self._push(self.gpu["busy"], g["busy"])
            self._push(self.gpu["vram"], 100 * g["vram_used"] / g["vram_total"] if g["vram_total"] else None)
            self._push(self.gpu["power"], 100 * g["power"] / g["power_cap"] if g["power"] and g["power_cap"] else None)
            self.latest["gpu"] = g
        return self.latest
