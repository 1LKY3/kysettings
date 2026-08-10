#!/usr/bin/env python3
"""KySettings - Custom GNOME Settings"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, Gio, GLib
import subprocess
import fcntl
import json
import os
import signal
import pathlib
from datetime import datetime, timedelta

FIRST_RUN_FLAG = pathlib.Path.home() / ".config" / "kysettings" / ".installed"
SS_CLEANUP_FLAG = pathlib.Path.home() / ".config" / "kysettings" / ".ss_cleanup"
WINDOW_STATE = pathlib.Path.home() / ".config" / "kysettings" / "window.json"
GAME_MUTE_SCRIPT = os.path.expanduser("~/.local/bin/game-auto-mute.py")
GAME_MUTE_AUTOSTART = pathlib.Path.home() / ".config" / "autostart" / "game-auto-mute.desktop"
GAME_MUTE_LOCK = pathlib.Path.home() / ".config" / "kysettings" / "game-auto-mute.lock"

# Written verbatim by the in-app Install button. Keep in sync with
# scripts/game-auto-mute, which install.sh copies into ~/.local/bin.
GAME_MUTE_SCRIPT_SOURCE = r'''#!/usr/bin/env python3
"""Auto-mute games when their window loses focus.

Watches _NET_ACTIVE_WINDOW (Xwayland/X11) and mutes every PipeWire output
stream that belongs to a game process which does not own the focused window.
Only streams this script muted are ever unmuted again, so a manual mute is
never undone. On exit everything it muted is restored.

Extra detection markers (one lowercase substring per line, matched against a
process's cmdline) can be added in ~/.config/kysettings/game-mute-markers.txt
"""

import fcntl
import json
import os
import re
import select
import signal
import subprocess
import sys
import pathlib

POLL_INTERVAL = 2.0  # re-scan even without a focus change, to catch new streams
MAX_ANCESTRY = 12

CONFIG_DIR = pathlib.Path.home() / ".config" / "kysettings"
EXTRA_MARKERS_FILE = CONFIG_DIR / "game-mute-markers.txt"
LOCK_FILE = CONFIG_DIR / "game-auto-mute.lock"

# A process is a game if any of these appear in its cmdline or an ancestor's.
GAME_MARKERS = (
    "/steamapps/",          # anything Steam actually installed
    "steamlaunch appid=",   # Steam's reaper wrapper
    "wine64-preloader",
    "wine-preloader",
    "wineserver",
    "/proton",
    "proton_dist",
    "lutris",
    "heroic",
    "bottles",
    "legendary",
    "prismlauncher",
    "multimc",
    "atlauncher",
    "minecraft",
)

# Never treat these as games even if a marker matches somewhere.
BINARY_DENYLIST = {
    "steam",
    "steamwebhelper",
    "steamerrorreporter",
    "pressure-vessel-adverb",
}

DEBUG = os.environ.get("GAME_AUTO_MUTE_DEBUG") == "1"


def log(msg):
    if DEBUG:
        print(msg, file=sys.stderr, flush=True)


def run(cmd):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return ""


def load_markers():
    markers = list(GAME_MARKERS)
    try:
        for line in EXTRA_MARKERS_FILE.read_text().splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                markers.append(line)
    except Exception:
        pass
    return tuple(markers)


MARKERS = load_markers()


# --------------------------------------------------------------------------
# process helpers
# --------------------------------------------------------------------------

def cmdline(pid):
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().replace(b"\0", b" ").decode("utf-8", "replace").lower()
    except OSError:
        return ""


def binary_name(pid):
    try:
        return os.path.basename(os.readlink(f"/proc/{pid}/exe")).lower()
    except OSError:
        return ""


def parent_of(pid):
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read().decode("utf-8", "replace")
        # comm can contain spaces/parens, so split after the final ')'
        return int(data[data.rindex(")") + 1:].split()[1])
    except (OSError, ValueError):
        return 0


def ancestry(pid):
    """pid plus its parents, closest first."""
    chain = []
    while pid and pid > 1 and len(chain) < MAX_ANCESTRY:
        chain.append(pid)
        pid = parent_of(pid)
    return chain


def is_game(pid):
    if binary_name(pid) in BINARY_DENYLIST:
        return False
    for ancestor in ancestry(pid):
        text = cmdline(ancestor)
        if any(marker in text for marker in MARKERS):
            return True
    return False


def same_process_group(a, b):
    """True if a and b are the same process or one is an ancestor of the other."""
    if not a or not b:
        return False
    if a == b:
        return True
    return a in ancestry(b) or b in ancestry(a)


# --------------------------------------------------------------------------
# pipewire helpers
# --------------------------------------------------------------------------

def audio_streams():
    """[(node_id, pid, name)] for every audio output stream."""
    try:
        dump = json.loads(run(["pw-dump"]) or "[]")
    except json.JSONDecodeError:
        return []

    streams = []
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = (obj.get("info") or {}).get("props") or {}
        if props.get("media.class") != "Stream/Output/Audio":
            continue
        pid = props.get("application.process.id")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            continue
        name = props.get("application.name") or props.get("node.name") or str(pid)
        streams.append((obj["id"], pid, name))
    return streams


def set_mute(node_id, muted):
    subprocess.run(
        ["wpctl", "set-mute", str(node_id), "1" if muted else "0"],
        capture_output=True,
    )


# --------------------------------------------------------------------------
# focus helpers
# --------------------------------------------------------------------------

def focused_pid():
    """PID owning the focused X window, or None (0x0 = a Wayland-native window)."""
    out = run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    match = re.search(r"(0x[0-9a-fA-F]+)", out)
    if not match or int(match.group(1), 16) == 0:
        return None
    out = run(["xprop", "-id", match.group(1), "_NET_WM_PID"])
    match = re.search(r"=\s*(\d+)", out)
    return int(match.group(1)) if match else None


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

muted_by_us = set()


def restore_all():
    for node_id in list(muted_by_us):
        set_mute(node_id, False)
    muted_by_us.clear()


def sync():
    focus = focused_pid()
    live = set()

    for node_id, pid, name in audio_streams():
        if not is_game(pid):
            continue
        live.add(node_id)
        if same_process_group(focus, pid):
            if node_id in muted_by_us:
                set_mute(node_id, False)
                muted_by_us.discard(node_id)
                log(f"unmute {name} (node {node_id})")
        elif node_id not in muted_by_us:
            set_mute(node_id, True)
            muted_by_us.add(node_id)
            log(f"mute {name} (node {node_id})")

    # streams that disappeared (game closed) no longer need restoring
    muted_by_us.intersection_update(live)


def acquire_lock():
    """Single-instance guard. Returns the fd, or None if already running."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.truncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def main():
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"

    if acquire_lock() is None:
        log("already running, exiting")
        return

    def bail(*_):
        restore_all()
        sys.exit(0)

    signal.signal(signal.SIGTERM, bail)
    signal.signal(signal.SIGINT, bail)
    signal.signal(signal.SIGHUP, bail)

    log(f"game-auto-mute started, {len(MARKERS)} markers")
    sync()

    spy = subprocess.Popen(
        ["xprop", "-root", "-spy", "_NET_ACTIVE_WINDOW"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        while spy.poll() is None:
            ready, _, _ = select.select([spy.stdout], [], [], POLL_INTERVAL)
            if ready:
                if not spy.stdout.readline():
                    break
            sync()
    finally:
        spy.terminate()
        restore_all()


if __name__ == "__main__":
    main()
'''

# Fallback only — the real size is whatever the window was last closed at.
# 1000 wide is the measured natural width of the six-tab view switcher; below
# that GTK ellipsises the page titles down to "...". 800 tall fits the longest
# page without scrolling.
DEFAULT_WINDOW_SIZE = (1000, 800)
# Restored sizes are clamped up to this so the titles stay readable on open.
MIN_WINDOW_SIZE = (1000, 700)


def load_window_state():
    """Return (width, height, maximized) from the last session."""
    try:
        state = json.loads(WINDOW_STATE.read_text())
        width = max(int(state["width"]), MIN_WINDOW_SIZE[0])
        height = max(int(state["height"]), MIN_WINDOW_SIZE[1])
        return width, height, bool(state.get("maximized", False))
    except Exception:
        return DEFAULT_WINDOW_SIZE[0], DEFAULT_WINDOW_SIZE[1], False


def save_window_state(win):
    """Remember the window size so it reopens the way it was left."""
    try:
        WINDOW_STATE.parent.mkdir(parents=True, exist_ok=True)
        width, height = win.get_default_size()
        WINDOW_STATE.write_text(json.dumps({
            "width": width,
            "height": height,
            "maximized": win.is_maximized(),
        }))
    except Exception as e:
        print(f"Failed to save window size: {e}")

# Mountain palette sampled from the shared K1/K2 Voidflow wallpaper.
# This provider is process-local: it themes KySettings without changing other
# GTK applications or replacing Ky's system-wide Yaru configuration.
MOUNTAIN_CSS = b"""
@define-color accent_color #A7B5C8;
@define-color accent_bg_color #5A6679;
@define-color accent_fg_color #FFFEFB;
@define-color destructive_color #FF8B7B;
@define-color destructive_bg_color #9C4F4A;
@define-color destructive_fg_color #FFFEFB;
@define-color success_color #A9C5AD;
@define-color success_bg_color #55725A;
@define-color success_fg_color #FFFEFB;
@define-color warning_color #E2C28F;
@define-color warning_bg_color #806B4C;
@define-color warning_fg_color #FFFEFB;
@define-color error_color #FF8B7B;
@define-color error_bg_color #9C4F4A;
@define-color error_fg_color #FFFEFB;
@define-color window_bg_color #0C121E;
@define-color window_fg_color #FFFDF8;
@define-color view_bg_color #111824;
@define-color view_fg_color #FFFDF8;
@define-color headerbar_bg_color #191E29;
@define-color headerbar_fg_color #FFFDF8;
@define-color headerbar_border_color #454E5F;
@define-color headerbar_backdrop_color #111824;
@define-color headerbar_shade_color rgba(7, 11, 19, 0.65);
@define-color card_bg_color #252D3B;
@define-color card_fg_color #FFFDF8;
@define-color card_shade_color rgba(7, 11, 19, 0.55);
@define-color dialog_bg_color #191E29;
@define-color dialog_fg_color #FFFDF8;
@define-color popover_bg_color #252D3B;
@define-color popover_fg_color #FFFDF8;
@define-color shade_color rgba(7, 11, 19, 0.60);
@define-color scrollbar_outline_color rgba(7, 11, 19, 0.75);

window.mountain-theme {
    background-color: #0C121E;
    color: #FFFDF8;
}

window.mountain-theme headerbar.mountain-header {
    background: linear-gradient(to bottom, #252D3B, #191E29);
    color: #FFFDF8;
    border-bottom: 1px solid #454E5F;
}

window.mountain-theme preferencespage,
window.mountain-theme .mountain-content {
    background-color: #0C121E;
    color: #FFFDF8;
}

window.mountain-theme actionrow,
window.mountain-theme expanderrow,
window.mountain-theme row {
    color: #FFFDF8;
}

window.mountain-theme button {
    border-color: alpha(#6E7582, 0.68);
}

window.mountain-theme button:hover {
    background-color: alpha(#6E7582, 0.32);
}

window.mountain-theme switch:checked,
window.mountain-theme scale highlight,
window.mountain-theme progressbar progress {
    background-color: #6E7582;
}

window.mountain-theme selection,
window.mountain-theme *:selected {
    background-color: #5A6679;
    color: #FFFEFB;
}
"""

# Custom keybinding paths
KEYBINDING_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"
KEYBINDING_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"

class KySettings(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.ky.settings')
        self.connect('activate', self.on_activate)

        # Timer state
        self.stopwatch_running = False
        self.stopwatch_start = None
        self.stopwatch_elapsed = timedelta()
        self.stopwatch_timer_id = None

        self.countdown_running = False
        self.countdown_remaining = timedelta()
        self.countdown_timer_id = None

        self.alarm_time = None
        self.alarm_enabled = False
        self.alarm_timer_id = None

        self._initializing = True

        # Screenshot cleanup loop (every hour)
        GLib.timeout_add_seconds(3600, self.cleanup_screenshots_loop)
        # Run once on startup too (after a short delay to not block UI)
        GLib.timeout_add_seconds(5, self.cleanup_screenshots_loop)

    def on_activate(self, app):
        self.install_mountain_theme()
        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_title("Ky Settings")
        width, height, maximized = load_window_state()
        self.win.set_default_size(width, height)
        if maximized:
            self.win.maximize()
        self.win.connect("close-request", self.on_window_close)
        self.win.add_css_class("mountain-theme")

        # Main layout
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        header.add_css_class("mountain-header")
        box.append(header)

        # Stack for multiple pages
        self.stack = Adw.ViewStack()
        self.stack.add_css_class("mountain-content")

        # Add pages
        self.add_display_page()
        self.add_effects_page()
        self.add_wireless_page()
        self.add_keyboard_page()
        self.add_timers_page()
        self.add_privacy_page()

        self._initializing = False

        # Switcher in header if multiple pages
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        box.append(self.stack)
        self.win.set_content(box)
        self.win.present()

        if not FIRST_RUN_FLAG.exists():
            self.pin_to_dash()
            self.show_welcome()
            FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
            FIRST_RUN_FLAG.touch()

    def on_window_close(self, win):
        """Save the window size on close so it reopens the same way."""
        save_window_state(win)
        return False

    def install_mountain_theme(self):
        """Apply the wallpaper-derived palette only inside KySettings."""
        if getattr(self, "mountain_css", None) is not None:
            return
        self.mountain_css = Gtk.CssProvider()
        self.mountain_css.load_from_data(MOUNTAIN_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self.mountain_css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def pin_to_dash(self):
        """Pin app to GNOME dash on first run."""
        try:
            settings = Gio.Settings.new("org.gnome.shell")
            favorites = list(settings.get_strv("favorite-apps"))
            if "com.ky.settings.desktop" not in favorites:
                favorites.append("com.ky.settings.desktop")
                settings.set_strv("favorite-apps", favorites)
        except Exception as e:
            print(f"Could not pin to dash: {e}")

    def show_welcome(self):
        dialog = Adw.MessageDialog(
            transient_for=self.win,
            heading="Welcome to Ky Settings",
            body=(
                "Ky Settings has been pinned to your dash.\n\n"
                "To remove it, open the Display page and toggle "
                "\"Pin to Dash\" off."
            ),
        )
        dialog.add_response("ok", "Got it")
        dialog.present()

    # (schema, key, kyle_value, ubuntu_default)
    DESKTOP_SETTINGS = [
        # Theme
        ("org.gnome.desktop.interface", "gtk-theme", "Yaru-sage-dark", "Yaru-dark"),
        ("org.gnome.desktop.interface", "color-scheme", "prefer-dark", "prefer-dark"),
        ("org.gnome.desktop.interface", "icon-theme", "Yaru-sage", "Yaru"),
        ("org.gnome.desktop.interface", "cursor-theme", "Yaru", "Yaru"),
        # Fonts
        ("org.gnome.desktop.interface", "font-name", "Ubuntu Sans 11", "Ubuntu Sans 11"),
        ("org.gnome.desktop.interface", "document-font-name", "Sans 11", "Sans 11"),
        ("org.gnome.desktop.interface", "monospace-font-name", "Ubuntu Sans Mono 13", "Ubuntu Mono 13"),
        # Wallpaper
        ("org.gnome.desktop.background", "picture-uri-dark",
         "file:///home/ky/Pictures/Wallpapers/voidflow-mountains.png",
         "file:///usr/share/backgrounds/ubuntu-wallpaper-d.png"),
        ("org.gnome.desktop.background", "picture-uri",
         "file:///home/ky/Pictures/Wallpapers/voidflow-mountains.png",
         "file:///usr/share/backgrounds/ubuntu-wallpaper-d.png"),
        ("org.gnome.desktop.background", "picture-options", "zoom", "zoom"),
        # Dock
        ("org.gnome.shell.extensions.dash-to-dock", "dock-position", "BOTTOM", "LEFT"),
        ("org.gnome.shell.extensions.dash-to-dock", "dash-max-icon-size", 38, 48),
        ("org.gnome.shell.extensions.dash-to-dock", "autohide", True, False),
        # Compositor
        ("org.gnome.mutter", "center-new-windows", False, False),
    ]

    def add_display_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Display")

        # Desktop Settings group
        desktop_group = Adw.PreferencesGroup()
        desktop_group.set_title("Desktop")
        desktop_group.set_description("Theme, wallpaper, fonts, and dock")

        desktop_row = Adw.SwitchRow()
        desktop_row.set_title("Kyle's Desktop")
        desktop_row.set_subtitle("ON = Kyle's settings / OFF = Ubuntu defaults")
        desktop_row.set_active(self._detect_kyle_desktop())
        desktop_row.connect("notify::active", self.on_desktop_toggle)
        desktop_group.add(desktop_row)

        hide_bar_row = Adw.SwitchRow()
        hide_bar_row.set_title("Hide Top Bar")
        hide_bar_row.set_subtitle("Auto-hide the GNOME top bar")
        hide_bar_row.set_active(self._is_hide_top_bar_enabled())
        hide_bar_row.connect("notify::active", self.on_hide_top_bar_toggle)
        desktop_group.add(hide_bar_row)

        logout_row = Adw.ActionRow()
        logout_row.set_title("Restart Session")
        logout_row.set_subtitle("Log out and back in to apply extension changes")
        logout_btn = Gtk.Button(label="Log Out")
        logout_btn.set_valign(Gtk.Align.CENTER)
        logout_btn.add_css_class("destructive-action")
        logout_btn.connect("clicked", self.on_restart_session)
        logout_row.add_suffix(logout_btn)
        desktop_group.add(logout_row)

        page.add(desktop_group)

        # Screen Off group
        group = Adw.PreferencesGroup()
        group.set_title("Screen Off")
        group.set_description("Monitor power off timeout")

        row = Adw.ComboRow()
        row.set_title("Turn Off Monitor After")

        self.blank_options = [
            ("Never", 0),
            ("1 minute", 60),
            ("2 minutes", 120),
            ("3 minutes", 180),
            ("5 minutes", 300),
            ("10 minutes", 600),
            ("15 minutes", 900),
            ("30 minutes", 1800),
            ("1 hour", 3600),
            ("2 hours", 7200),
            ("3 hours", 10800),
            ("4 hours", 14400),
        ]

        model = Gtk.StringList()
        for label, _ in self.blank_options:
            model.append(label)
        row.set_model(model)

        # Current value
        settings = Gio.Settings.new("org.gnome.desktop.session")
        current = settings.get_uint("idle-delay")
        for i, (_, val) in enumerate(self.blank_options):
            if val == current:
                row.set_selected(i)
                break

        row.connect("notify::selected", self.on_blank_changed)
        group.add(row)

        # Apply DPMS monitor-off on startup to match current setting
        self._set_monitor_off(current)

        page.add(group)

        # Application group
        app_group = Adw.PreferencesGroup()
        app_group.set_title("Application")

        # Pin to dash toggle
        pin_row = Adw.SwitchRow()
        pin_row.set_title("Pin to Dash")
        pin_row.set_subtitle("Keep Ky Settings in the dock")
        pin_row.set_active(self.is_pinned_to_dash())
        pin_row.connect("notify::active", self.on_pin_toggle)
        app_group.add(pin_row)

        page.add(app_group)

        # Audio/Gaming group
        audio_group = Adw.PreferencesGroup()
        audio_group.set_title("Gaming")

        # Game auto-mute install row
        mc_install_row = Adw.ActionRow()
        mc_install_row.set_title("Game Auto-Mute Script")
        mc_install_row.set_subtitle("Covers Steam/Proton, Minecraft, Lutris, Heroic and Bottles")
        self.game_mute_btn = Gtk.Button(label="Installed" if self.is_game_mute_installed() else "Install")
        self.game_mute_btn.set_valign(Gtk.Align.CENTER)
        self.game_mute_btn.set_sensitive(not self.is_game_mute_installed())
        self.game_mute_btn.connect("clicked", self.on_game_mute_install)
        mc_install_row.add_suffix(self.game_mute_btn)
        audio_group.add(mc_install_row)

        # Game auto-mute toggle
        mc_mute_row = Adw.SwitchRow()
        mc_mute_row.set_title("Game Auto-Mute")
        mc_mute_row.set_subtitle("Mute any running game while its window is not focused")
        mc_mute_row.set_active(self.is_game_mute_enabled())
        mc_mute_row.set_sensitive(self.is_game_mute_installed())
        mc_mute_row.connect("notify::active", self.on_game_mute_toggle)
        audio_group.add(mc_mute_row)
        self.game_mute_row = mc_mute_row

        page.add(audio_group)

        # Dock group
        dock_group = Adw.PreferencesGroup()
        dock_group.set_title("Dock")

        minimize_row = Adw.SwitchRow()
        minimize_row.set_title("Minimize on Right-Click")
        pending = (self._is_dash_minimize_enabled() and
                   not self._is_dash_minimize_loaded())
        minimize_row.set_subtitle("Log out and back in to load the extension"
                                  if pending else self.DASH_MINIMIZE_SUBTITLE)
        minimize_row.set_active(self._is_dash_minimize_enabled())
        minimize_row.connect("notify::active", self.on_dash_minimize_toggle)
        dock_group.add(minimize_row)
        self.dash_minimize_row = minimize_row

        # Only shown while the toggle is on but the shell has not loaded the
        # extension yet, i.e. between the first switch-on and the next login.
        pending_row = Adw.ActionRow()
        pending_row.set_title("Finish Enabling")
        pending_row.set_subtitle("The extension loads at your next login")
        pending_btn = Gtk.Button(label="Log Out")
        pending_btn.set_valign(Gtk.Align.CENTER)
        pending_btn.add_css_class("destructive-action")
        pending_btn.connect("clicked", self.on_restart_session)
        pending_row.add_suffix(pending_btn)
        pending_row.set_visible(pending)
        dock_group.add(pending_row)
        self.dash_minimize_pending_row = pending_row

        page.add(dock_group)

        self.stack.add_titled(page, "display", "Display")

    def is_pinned_to_dash(self):
        """Check if app is in GNOME favorites."""
        try:
            settings = Gio.Settings.new("org.gnome.shell")
            favorites = settings.get_strv("favorite-apps")
            return "com.ky.settings.desktop" in favorites
        except:
            return False

    def on_pin_toggle(self, row, _):
        """Add or remove app from GNOME dash favorites."""
        if self._initializing:
            return
        try:
            settings = Gio.Settings.new("org.gnome.shell")
            favorites = list(settings.get_strv("favorite-apps"))

            if row.get_active():
                if "com.ky.settings.desktop" not in favorites:
                    favorites.append("com.ky.settings.desktop")
            else:
                if "com.ky.settings.desktop" in favorites:
                    favorites.remove("com.ky.settings.desktop")

            settings.set_strv("favorite-apps", favorites)
        except Exception as e:
            print(f"Error toggling pin: {e}")

    def _detect_kyle_desktop(self):
        """Check if current desktop matches Kyle's settings (by gtk-theme)."""
        try:
            s = Gio.Settings.new("org.gnome.desktop.interface")
            return s.get_string("gtk-theme") == "Yaru-sage-dark"
        except Exception:
            return False

    def on_desktop_toggle(self, row, _pspec):
        """Toggle between Kyle's desktop settings and Ubuntu defaults."""
        if self._initializing:
            return
        use_kyle = row.get_active()
        # Index 2 = kyle_value, index 3 = ubuntu_default
        idx = 2 if use_kyle else 3
        applied = 0
        errors = []
        for entry in self.DESKTOP_SETTINGS:
            schema, key, kyle_val, default_val = entry
            value = kyle_val if use_kyle else default_val
            try:
                s = Gio.Settings.new(schema)
                if isinstance(value, bool):
                    s.set_boolean(key, value)
                elif isinstance(value, int):
                    s.set_int(key, value)
                else:
                    s.set_string(key, value)
                applied += 1
            except Exception as e:
                errors.append(f"{schema}.{key}: {e}")

        label = "Kyle's settings" if use_kyle else "Ubuntu defaults"
        if errors:
            body = f"Applied {applied} {label}.\n{len(errors)} failed:\n" + "\n".join(errors[:5])
        else:
            body = f"{label} applied ({applied} settings)."

        dialog = Adw.MessageDialog(
            transient_for=self.win,
            heading="Desktop Updated",
            body=body,
        )
        dialog.add_response("ok", "OK")
        dialog.present()

    HIDE_TOP_BAR_UUID = "hidetopbar@mathieu.bidon.ca"

    def on_restart_session(self, button):
        """Log out with confirmation dialog."""
        dialog = Adw.MessageDialog(
            transient_for=self.win,
            heading="Log Out?",
            body="This will end your session. Unsaved work will be lost.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("logout", "Log Out")
        dialog.set_response_appearance("logout", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_logout_response)
        dialog.present()

    def _on_logout_response(self, dialog, response):
        if response == "logout":
            subprocess.Popen(["gnome-session-quit", "--no-prompt"])

    def _is_hide_top_bar_enabled(self):
        """Check if Hide Top Bar extension is installed and active."""
        try:
            result = subprocess.run(
                ["gnome-extensions", "info", self.HIDE_TOP_BAR_UUID],
                capture_output=True, text=True, timeout=5
            )
            return "State: ACTIVE" in result.stdout or "State: ENABLED" in result.stdout
        except Exception:
            return False

    def _is_hide_top_bar_installed(self):
        """Check if Hide Top Bar extension is installed."""
        try:
            result = subprocess.run(
                ["gnome-extensions", "info", self.HIDE_TOP_BAR_UUID],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _install_hide_top_bar_via_dbus(self):
        """Install Hide Top Bar via GNOME Shell dbus (triggers scan + enable)."""
        try:
            subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.gnome.Shell.Extensions",
                 "--object-path", "/org/gnome/Shell/Extensions",
                 "--method", "org.gnome.Shell.Extensions.InstallRemoteExtension",
                 self.HIDE_TOP_BAR_UUID],
                capture_output=True, timeout=15
            )
            return True
        except Exception as e:
            print(f"Failed to install Hide Top Bar via dbus: {e}")
            return False

    def on_hide_top_bar_toggle(self, row, _pspec):
        """Enable or disable the Hide Top Bar extension."""
        if self._initializing:
            return
        enable = row.get_active()

        if enable and not self._is_hide_top_bar_installed():
            row.set_subtitle("Installing extension...")
            if not self._install_hide_top_bar_via_dbus():
                row.set_subtitle("Install failed — check internet connection")
                row.set_active(False)
                return
            # dbus install auto-enables, so we're done
            row.set_subtitle("Auto-hide the GNOME top bar")
            return

        action = "enable" if enable else "disable"
        try:
            subprocess.run(
                ["gnome-extensions", action, self.HIDE_TOP_BAR_UUID],
                capture_output=True, timeout=5
            )
        except Exception as e:
            print(f"Failed to {action} Hide Top Bar: {e}")
            row.set_active(not enable)
        row.set_subtitle("Auto-hide the GNOME top bar")

    DASH_MINIMIZE_UUID = "dash-minimize@ky.local"
    DASH_MINIMIZE_SUBTITLE = "Add a Minimize entry to dock icon right-click menus"

    def _is_dash_minimize_installed(self):
        """Extension files are on disk (whether or not the shell has loaded them)."""
        return os.path.isdir(os.path.expanduser(
            f"~/.local/share/gnome-shell/extensions/{self.DASH_MINIMIZE_UUID}"))

    def _is_dash_minimize_loaded(self):
        """The running shell knows about the extension, so toggling is live."""
        try:
            result = subprocess.run(
                ["gnome-extensions", "info", self.DASH_MINIMIZE_UUID],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _is_dash_minimize_enabled(self):
        """`gnome-extensions enable` refuses extensions the shell has not scanned
        yet, so the enabled-extensions key is the state that survives either way:
        the shell applies it live when loaded, and at the next login when not."""
        try:
            settings = Gio.Settings.new("org.gnome.shell")
            return self.DASH_MINIMIZE_UUID in settings.get_strv("enabled-extensions")
        except Exception:
            return False

    def on_dash_minimize_toggle(self, row, _pspec):
        """Enable or disable the Dash Minimize extension."""
        if self._initializing:
            return
        enable = row.get_active()

        if enable and not self._is_dash_minimize_installed():
            row.set_subtitle("Not installed — run ./install.sh from the kysettings repo")
            row.set_active(False)
            return

        try:
            settings = Gio.Settings.new("org.gnome.shell")
            enabled = settings.get_strv("enabled-extensions")
            if enable and self.DASH_MINIMIZE_UUID not in enabled:
                enabled.append(self.DASH_MINIMIZE_UUID)
            elif not enable and self.DASH_MINIMIZE_UUID in enabled:
                enabled.remove(self.DASH_MINIMIZE_UUID)
            settings.set_strv("enabled-extensions", enabled)

            disabled = settings.get_strv("disabled-extensions")
            if enable and self.DASH_MINIMIZE_UUID in disabled:
                disabled.remove(self.DASH_MINIMIZE_UUID)
                settings.set_strv("disabled-extensions", disabled)
        except Exception as e:
            print(f"Failed to toggle Dash Minimize: {e}")
            row.set_active(not enable)
            row.set_subtitle(self.DASH_MINIMIZE_SUBTITLE)
            return

        pending = enable and not self._is_dash_minimize_loaded()
        row.set_subtitle("Log out and back in to load the extension"
                         if pending else self.DASH_MINIMIZE_SUBTITLE)
        self.dash_minimize_pending_row.set_visible(pending)

    def is_game_mute_installed(self):
        """Check if the game auto-mute script is installed."""
        return os.path.exists(GAME_MUTE_SCRIPT)

    def is_game_mute_running(self):
        """True if the daemon holds its single-instance lock.

        Deliberately not `pgrep -f`: that matches any command line which merely
        mentions the script, which made the switch read as "on" while nothing
        was actually running.
        """
        try:
            fd = os.open(GAME_MUTE_LOCK, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            return False
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False
        finally:
            os.close(fd)

    def game_mute_pid(self):
        """PID recorded by the running daemon, or None."""
        try:
            return int(GAME_MUTE_LOCK.read_text().strip())
        except (OSError, ValueError):
            return None

    def stop_game_mute(self):
        """Stop the daemon by PID so it can unmute what it muted."""
        pid = self.game_mute_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def is_game_mute_enabled(self):
        """The switch is on if the daemon runs now or is set to run at login."""
        return GAME_MUTE_AUTOSTART.exists() or self.is_game_mute_running()

    def set_game_mute_autostart(self, enabled):
        """Add or remove the autostart entry so the toggle survives a reboot."""
        try:
            if enabled:
                GAME_MUTE_AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                GAME_MUTE_AUTOSTART.write_text(
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=Game Auto-Mute\n"
                    "Comment=Mute games while their window is not focused\n"
                    f"Exec={GAME_MUTE_SCRIPT}\n"
                    "X-GNOME-Autostart-enabled=true\n"
                    "NoDisplay=true\n"
                )
            else:
                GAME_MUTE_AUTOSTART.unlink(missing_ok=True)
        except Exception as e:
            print(f"Failed to update game auto-mute autostart: {e}")

    def on_game_mute_install(self, button):
        """Install the game auto-mute script and its dependencies."""
        button.set_sensitive(False)
        button.set_label("Installing...")

        # xprop/xdotool come from x11-utils and xdotool
        for tool, pkg in (("xprop", "x11-utils"), ("xdotool", "xdotool")):
            try:
                subprocess.run(["which", tool], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                subprocess.Popen(
                    ["pkexec", "apt", "install", "-y", pkg],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        os.makedirs(os.path.dirname(GAME_MUTE_SCRIPT), exist_ok=True)
        with open(GAME_MUTE_SCRIPT, "w") as f:
            f.write(GAME_MUTE_SCRIPT_SOURCE)
        os.chmod(GAME_MUTE_SCRIPT, 0o755)

        GLib.timeout_add(3000, self._game_mute_install_done)

    def _game_mute_install_done(self):
        if self.is_game_mute_installed():
            self.game_mute_btn.set_label("Installed")
            self.game_mute_row.set_sensitive(True)
        else:
            self.game_mute_btn.set_label("Install")
            self.game_mute_btn.set_sensitive(True)
        return False

    def on_game_mute_toggle(self, row, _):
        """Start or stop the game auto-mute script."""
        if self._initializing:
            return

        if row.get_active():
            # The old Minecraft-only daemon would fight this one over the same
            # streams, so retire it if it is still running.
            subprocess.run(["pkill", "-f", "minecraft-auto-mute"], capture_output=True)
            self.set_game_mute_autostart(True)
            # The daemon takes its own lock, so a double-start is harmless.
            subprocess.Popen(
                [GAME_MUTE_SCRIPT],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        else:
            self.set_game_mute_autostart(False)
            self.stop_game_mute()


    # =========================================================================
    # EFFECTS PAGE
    # =========================================================================

    def add_effects_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Effects")

        bms_installed = self._is_blur_my_shell_installed()

        # ── Group: Blur my Shell ─────────────────────────────────────────────
        bms_group = Adw.PreferencesGroup()
        bms_group.set_title("Blur my Shell")
        bms_group.set_description("Open-source GNOME extension for frosted glass effects")

        bms_row = Adw.ActionRow()
        bms_row.set_title("Extension Status")
        if bms_installed:
            bms_row.set_subtitle("Installed and active")
            ok_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            ok_icon.add_css_class("success")
            ok_icon.set_valign(Gtk.Align.CENTER)
            bms_row.add_suffix(ok_icon)
        else:
            bms_row.set_subtitle("Required for effects — installs via pip + gnome-extensions")
            self.bms_install_btn = Gtk.Button(label="Install")
            self.bms_install_btn.set_valign(Gtk.Align.CENTER)
            self.bms_install_btn.add_css_class("suggested-action")
            self.bms_install_btn.connect("clicked", self.on_blur_my_shell_install)
            bms_row.add_suffix(self.bms_install_btn)
        bms_group.add(bms_row)
        page.add(bms_group)

        # ── Group: Application Windows ───────────────────────────────────────
        app_group = Adw.PreferencesGroup()
        app_group.set_title("Application Windows")
        app_group.set_description("Blur and transparency for all open windows")
        app_group.set_sensitive(bms_installed)

        app_blur_row = Adw.SwitchRow()
        app_blur_row.set_title("Enable Window Effects")
        app_blur_row.set_subtitle("Apply blur and transparency to all app windows")
        app_blur_row.set_active(self._bms_get_bool("applications", "blur"))
        app_blur_row.connect("notify::active", self.on_app_effects_toggle)
        app_group.add(app_blur_row)

        # Blur amount slider
        blur_row = Adw.ActionRow()
        blur_row.set_title("Blur Amount")
        blur_row.set_subtitle("Radius of the frosted glass blur")
        blur_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 50, 1)
        blur_scale.set_value(self._bms_get_int("applications", "sigma"))
        blur_scale.set_size_request(220, -1)
        blur_scale.set_valign(Gtk.Align.CENTER)
        blur_scale.set_draw_value(True)
        blur_scale.add_mark(0,  Gtk.PositionType.BOTTOM, "Off")
        blur_scale.add_mark(50, Gtk.PositionType.BOTTOM, "Max")
        blur_scale.connect("value-changed", self.on_blur_sigma_changed)
        blur_row.add_suffix(blur_scale)
        app_group.add(blur_row)

        # Transparency slider
        trans_row = Adw.ActionRow()
        trans_row.set_title("Transparency")
        trans_row.set_subtitle("How see-through windows appear")
        trans_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        opacity_raw = self._bms_get_int("applications", "opacity")
        trans_scale.set_value(round((255 - opacity_raw) / 255 * 100))
        trans_scale.set_size_request(220, -1)
        trans_scale.set_valign(Gtk.Align.CENTER)
        trans_scale.set_draw_value(True)
        trans_scale.set_format_value_func(lambda _, v: f"{int(v)}%")
        trans_scale.add_mark(0,   Gtk.PositionType.BOTTOM, "Solid")
        trans_scale.add_mark(100, Gtk.PositionType.BOTTOM, "Clear")
        trans_scale.connect("value-changed", self.on_transparency_changed)
        trans_row.add_suffix(trans_scale)
        app_group.add(trans_row)

        page.add(app_group)

        # ── Group: Panel & Overview ──────────────────────────────────────────
        panel_group = Adw.PreferencesGroup()
        panel_group.set_title("Panel and Overview")
        panel_group.set_description("Blur effects for the top bar and activities overview")
        panel_group.set_sensitive(bms_installed)

        panel_row = Adw.SwitchRow()
        panel_row.set_title("Blur Top Bar")
        panel_row.set_subtitle("Frosted glass on the GNOME top bar")
        panel_row.set_active(self._bms_get_bool("panel", "blur"))
        panel_row.connect("notify::active", self.on_panel_blur_toggle)
        panel_group.add(panel_row)

        overview_row = Adw.SwitchRow()
        overview_row.set_title("Blur Overview")
        overview_row.set_subtitle("Blur the desktop when pressing Super")
        overview_row.set_active(self._bms_get_bool("overview", "blur"))
        overview_row.connect("notify::active", self.on_overview_blur_toggle)
        panel_group.add(overview_row)

        page.add(panel_group)

        self.stack.add_titled(page, "effects", "Effects")

    # ── Blur my Shell helpers ─────────────────────────────────────────────────

    def _is_blur_my_shell_installed(self):
        try:
            result = subprocess.run(
                ["gnome-extensions", "list"],
                capture_output=True, text=True, timeout=5
            )
            return "blur-my-shell@aunetx" in result.stdout
        except Exception:
            return False

    def _bms_schema(self, sub):
        """Return a Settings object for a BMS sub-schema, or None if not installed."""
        schema_id = f"org.gnome.shell.extensions.blur-my-shell.{sub}"
        source = Gio.SettingsSchemaSource.get_default()
        if source and source.lookup(schema_id, True):
            return Gio.Settings.new(schema_id)
        return None

    def _bms_get_bool(self, sub, key):
        s = self._bms_schema(sub)
        return s.get_boolean(key) if s else False

    def _bms_get_int(self, sub, key):
        s = self._bms_schema(sub)
        return s.get_int(key) if s else 0

    def _bms_set_bool(self, sub, key, value):
        s = self._bms_schema(sub)
        if s:
            s.set_boolean(key, value)

    def _bms_set_int(self, sub, key, value):
        s = self._bms_schema(sub)
        if s:
            s.set_int(key, value)

    # ── Effects event handlers ────────────────────────────────────────────────

    def on_app_effects_toggle(self, row, _):
        self._bms_set_bool("applications", "blur", row.get_active())

    def on_blur_sigma_changed(self, scale):
        self._bms_set_int("applications", "sigma", int(scale.get_value()))

    def on_transparency_changed(self, scale):
        opacity = round((100 - scale.get_value()) / 100 * 255)
        self._bms_set_int("applications", "opacity", opacity)

    def on_panel_blur_toggle(self, row, _):
        self._bms_set_bool("panel", "blur", row.get_active())

    def on_overview_blur_toggle(self, row, _):
        self._bms_set_bool("overview", "blur", row.get_active())

    def on_blur_my_shell_install(self, button):
        button.set_sensitive(False)
        button.set_label("Installing…")
        import threading
        threading.Thread(target=self._install_blur_my_shell, daemon=True).start()

    def _install_blur_my_shell(self):
        import shutil
        try:
            # Install gnome-extensions-cli (provides `gext`) if not present
            if not shutil.which("gext") and not os.path.exists(os.path.expanduser("~/.local/bin/gext")):
                subprocess.run(
                    ["pip3", "install", "--user", "--quiet", "gnome-extensions-cli"],
                    capture_output=True, timeout=90
                )
            gext = shutil.which("gext") or os.path.expanduser("~/.local/bin/gext")
            subprocess.run([gext, "install", "blur-my-shell@aunetx"],
                           capture_output=True, timeout=90)
            subprocess.run(["gnome-extensions", "enable", "blur-my-shell@aunetx"],
                           capture_output=True, timeout=10)
            success = self._is_blur_my_shell_installed()
        except Exception:
            success = False
        GLib.idle_add(self._blur_install_done, success)

    def _blur_install_done(self, success):
        if success:
            self.bms_install_btn.set_label("Installed — log out to activate")
            self.bms_install_btn.add_css_class("success")
        else:
            self.bms_install_btn.set_label("Install")
            self.bms_install_btn.set_sensitive(True)
        return False

    def add_wireless_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Wireless")

        # Bluetooth group
        bt_group = Adw.PreferencesGroup()
        bt_group.set_title("Bluetooth")

        bt_power_row = Adw.SwitchRow()
        bt_power_row.set_title("Bluetooth")
        bt_power_row.set_subtitle("Turn adapter on or off")
        bt_power_row.set_active(self.is_bluetooth_powered())
        bt_power_row.connect("notify::active", self.on_bluetooth_power_toggle)
        bt_group.add(bt_power_row)
        self.bt_power_row = bt_power_row

        bt_reset_row = Adw.ActionRow()
        bt_reset_row.set_title("Reset Adapter")
        bt_reset_row.set_subtitle("Reset adapter, scan, and reconnect devices")
        bt_reset_btn = Gtk.Button(label="Reset")
        bt_reset_btn.set_valign(Gtk.Align.CENTER)
        bt_reset_btn.connect("clicked", self.on_bluetooth_reset)
        bt_reset_row.add_suffix(bt_reset_btn)
        bt_group.add(bt_reset_row)

        page.add(bt_group)

        # PDANet+ Proxy group
        pda_group = Adw.PreferencesGroup()
        pda_group.set_title("PDANet+ Proxy")
        pda_group.set_description("Route traffic through PDANet+ WiFi tether")

        # System proxy toggle (gsettings — browsers, GUI apps, CLI tools)
        pda_toggle_row = Adw.SwitchRow()
        pda_toggle_row.set_title("PDANet+ Proxy")
        pda_toggle_row.set_subtitle("192.168.49.1:8000 — system proxy via tether")
        pda_toggle_row.set_active(self.is_pdanet_proxy_active())
        pda_toggle_row.connect("notify::active", self.on_pdanet_proxy_toggle)
        pda_group.add(pda_toggle_row)
        self.pda_toggle_row = pda_toggle_row

        # Redsocks — transparent proxy for ALL TCP traffic
        pda_redsocks_toggle = Adw.SwitchRow()
        pda_redsocks_toggle.set_title("Transparent Proxy (redsocks)")
        if self.is_redsocks_installed():
            pda_redsocks_toggle.set_subtitle("All TCP traffic via iptables — captures every app")
            pda_redsocks_toggle.set_active(self.is_redsocks_proxy_running())
        else:
            pda_redsocks_toggle.set_subtitle("redsocks missing — run ./install.sh to fix")
            pda_redsocks_toggle.set_sensitive(False)
        pda_redsocks_toggle.connect("notify::active", self.on_redsocks_proxy_toggle)
        pda_group.add(pda_redsocks_toggle)
        self.pda_redsocks_toggle = pda_redsocks_toggle

        page.add(pda_group)
        self.stack.add_titled(page, "wireless", "Wireless")

    def is_bluetooth_powered(self):
        """Check if Bluetooth adapter is powered on."""
        try:
            result = subprocess.run(
                ["bluetoothctl", "show"],
                capture_output=True, text=True, timeout=5
            )
            return "Powered: yes" in result.stdout
        except:
            return False

    def on_bluetooth_power_toggle(self, row, _):
        """Toggle Bluetooth adapter power."""
        if self._initializing:
            return
        state = "on" if row.get_active() else "off"
        subprocess.run(
            ["bluetoothctl", "power", state],
            capture_output=True, timeout=5
        )

    def on_bluetooth_reset(self, button):
        """Full reset: adapter reset + scan + reconnect paired devices."""
        button.set_sensitive(False)
        button.set_label("Resetting...")
        self._bt_reset_proc = subprocess.Popen(
            ["pkexec", os.path.expanduser("~/.local/bin/bt-reset")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Poll every 2s until the process finishes (up to 60s)
        self._bt_reset_polls = 0
        GLib.timeout_add(2000, self._bluetooth_reset_poll, button)

    def _bluetooth_reset_poll(self, button):
        self._bt_reset_polls += 1
        ret = self._bt_reset_proc.poll()
        if ret is None and self._bt_reset_polls < 30:
            # Still running — update label with elapsed time
            elapsed = self._bt_reset_polls * 2
            button.set_label(f"Resetting... ({elapsed}s)")
            return True  # keep polling
        # Done (or timed out)
        button.set_sensitive(True)
        # Check if A2DP came up by reading the log
        try:
            log = open("/tmp/bt-reset.log").read()
            if "A2DP transport verified OK" in log:
                button.set_label("Reset ✓")
            else:
                button.set_label("Reset (no A2DP)")
        except Exception:
            button.set_label("Reset")
        self._bluetooth_refresh_state()
        GLib.timeout_add(5000, self._bluetooth_reset_label_clear, button)
        return False

    def _bluetooth_reset_label_clear(self, button):
        button.set_label("Reset")
        return False

    def _bluetooth_refresh_state(self):
        powered = self.is_bluetooth_powered()
        self.bt_power_row.set_active(powered)
        return False

    # === PDANET+ PROXY FUNCTIONS ===
    def is_redsocks_installed(self):
        """Check if redsocks is installed."""
        try:
            result = subprocess.run(["which", "redsocks"], capture_output=True)
            return result.returncode == 0
        except:
            return False


    def is_redsocks_proxy_running(self):
        """Check if redsocks transparent proxy is active (no root needed)."""
        try:
            result = subprocess.run(
                [os.path.expanduser("~/.local/bin/pdanet-proxy"), "status"],
                capture_output=True, text=True, timeout=5
            )
            return "running" in result.stdout
        except:
            return False

    def on_redsocks_proxy_toggle(self, row, _):
        """Start or stop the redsocks transparent proxy."""
        if self._initializing:
            return
        script = os.path.expanduser("~/.local/bin/pdanet-proxy")
        if row.get_active():
            self._redsocks_action = "start"
            self._redsocks_proc = subprocess.Popen(
                ["pkexec", script, "start"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        else:
            self._redsocks_action = "stop"
            self._redsocks_proc = subprocess.Popen(
                ["pkexec", script, "stop"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        GLib.timeout_add(500, self._redsocks_poll, row)

    def _redsocks_poll(self, row):
        """Poll until pkexec process finishes, then verify."""
        if hasattr(self, '_redsocks_proc') and self._redsocks_proc:
            rc = self._redsocks_proc.poll()
            if rc is None:
                # Still running (user typing password) — check again in 500ms
                return True

            output = ""
            try:
                output = self._redsocks_proc.stdout.read().decode(errors='replace')
            except Exception:
                pass

            running = self.is_redsocks_proxy_running()
            wanted = self._redsocks_action == "start"

            if running != wanted:
                self._initializing = True
                row.set_active(running)
                self._initializing = False
                msg = output.strip() if output.strip() else (
                    "Could not start proxy. Is PDANet WiFi connected?"
                    if wanted else "Could not stop proxy."
                )
                dialog = Adw.MessageDialog(
                    transient_for=self.win,
                    heading="Proxy Error",
                    body=msg,
                )
                dialog.add_response("ok", "OK")
                dialog.present()
        return False

    _PDANET_PROXY_HOST = "192.168.49.1"
    _PDANET_PROXY_PORT = 8000
    _PDANET_IGNORE_HOSTS = "['localhost', '127.0.0.0/8', '::1', '192.168.49.*']"
    _PDANET_ENV_FILE = os.path.expanduser("~/.proxy_env")

    def is_pdanet_proxy_active(self):
        """Check if GNOME system proxy is set to PDANet+."""
        try:
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.system.proxy", "mode"],
                capture_output=True, text=True, timeout=5
            )
            if "'manual'" not in result.stdout:
                return False
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.system.proxy.http", "host"],
                capture_output=True, text=True, timeout=5
            )
            return self._PDANET_PROXY_HOST in result.stdout
        except:
            return False

    def on_pdanet_proxy_toggle(self, row, _):
        """Toggle PDANet+ system proxy via GNOME gsettings."""
        if self._initializing:
            return
        if row.get_active():
            self._pdanet_proxy_enable()
        else:
            self._pdanet_proxy_disable()

    def _pdanet_proxy_enable(self):
        """Set GNOME system proxy + env vars for CLI tools."""
        host = self._PDANET_PROXY_HOST
        port = str(self._PDANET_PROXY_PORT)
        proxy_url = f"http://{host}:{port}"

        # 1. GNOME system proxy (browsers, GUI apps)
        cmds = [
            ["gsettings", "set", "org.gnome.system.proxy", "mode", "manual"],
            ["gsettings", "set", "org.gnome.system.proxy.http", "host", host],
            ["gsettings", "set", "org.gnome.system.proxy.http", "port", port],
            ["gsettings", "set", "org.gnome.system.proxy.https", "host", host],
            ["gsettings", "set", "org.gnome.system.proxy.https", "port", port],
            ["gsettings", "set", "org.gnome.system.proxy", "ignore-hosts", self._PDANET_IGNORE_HOSTS],
        ]
        for cmd in cmds:
            subprocess.run(cmd, capture_output=True, timeout=5)

        # 2. Env var file sourced by shells (curl, wget, git, apt, pip, etc.)
        no_proxy = "localhost,127.0.0.0/8,::1,192.168.49.*"
        env_content = (
            f'export http_proxy="{proxy_url}"\n'
            f'export https_proxy="{proxy_url}"\n'
            f'export HTTP_PROXY="{proxy_url}"\n'
            f'export HTTPS_PROXY="{proxy_url}"\n'
            f'export no_proxy="{no_proxy}"\n'
            f'export NO_PROXY="{no_proxy}"\n'
        )
        try:
            with open(self._PDANET_ENV_FILE, "w") as f:
                f.write(env_content)
        except Exception:
            pass

        # Ensure bashrc sources the env file
        self._ensure_bashrc_hook()

        # 3. apt proxy (needs its own config)
        apt_conf = f'Acquire::http::Proxy "{proxy_url}";\nAcquire::https::Proxy "{proxy_url}";\n'
        try:
            subprocess.run(
                ["pkexec", "bash", "-c", f'echo \'{apt_conf}\' > /etc/apt/apt.conf.d/99pdanet-proxy'],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass

    def _pdanet_proxy_disable(self):
        """Reset all proxy settings to defaults."""
        # 1. GNOME system proxy
        cmds = [
            ["gsettings", "set", "org.gnome.system.proxy", "mode", "none"],
            ["gsettings", "reset", "org.gnome.system.proxy.http", "host"],
            ["gsettings", "reset", "org.gnome.system.proxy.http", "port"],
            ["gsettings", "reset", "org.gnome.system.proxy.https", "host"],
            ["gsettings", "reset", "org.gnome.system.proxy.https", "port"],
            ["gsettings", "reset", "org.gnome.system.proxy", "ignore-hosts"],
        ]
        for cmd in cmds:
            subprocess.run(cmd, capture_output=True, timeout=5)

        # 2. Remove env var file
        try:
            os.remove(self._PDANET_ENV_FILE)
        except FileNotFoundError:
            pass

        # 3. Remove apt proxy config
        try:
            subprocess.run(
                ["pkexec", "rm", "-f", "/etc/apt/apt.conf.d/99pdanet-proxy"],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass

    def _ensure_bashrc_hook(self):
        """Add proxy_env source line to ~/.bashrc if not already present."""
        bashrc = os.path.expanduser("~/.bashrc")
        hook = '[ -f ~/.proxy_env ] && . ~/.proxy_env'
        try:
            existing = ""
            if os.path.exists(bashrc):
                with open(bashrc, "r") as f:
                    existing = f.read()
            if hook not in existing:
                with open(bashrc, "a") as f:
                    f.write(f"\n# PDANet proxy env vars (managed by kysettings)\n{hook}\n")
        except Exception:
            pass

    def on_blank_changed(self, row, _):
        if self._initializing:
            return
        _, seconds = self.blank_options[row.get_selected()]
        # Set GNOME idle-delay (controls when screen action triggers)
        Gio.Settings.new("org.gnome.desktop.session").set_uint("idle-delay", seconds)
        # Use DPMS to power off the monitor (not just blank)
        self._set_monitor_off(seconds)

    def _set_monitor_off(self, seconds):
        """Configure DPMS to turn monitor OFF instead of just blanking."""
        # Disable screensaver blanking — we want DPMS power off instead
        subprocess.run(
            ["gsettings", "set", "org.gnome.desktop.screensaver", "idle-activation-enabled", "false"],
            capture_output=True, timeout=5
        )
        # Disable idle dimming
        subprocess.run(
            ["gsettings", "set", "org.gnome.settings-daemon.plugins.power", "idle-dim", "false"],
            capture_output=True, timeout=5
        )
        if seconds == 0:
            # "Never" — disable DPMS entirely
            subprocess.run(["xset", "dpms", "0", "0", "0"], capture_output=True, timeout=5)
            subprocess.run(["xset", "-dpms"], capture_output=True, timeout=5)
        else:
            # Set DPMS: no standby, no suspend, off after <seconds>
            subprocess.run(["xset", "dpms", "0", "0", str(seconds)], capture_output=True, timeout=5)
            subprocess.run(["xset", "+dpms"], capture_output=True, timeout=5)

    def add_keyboard_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Keyboard")

        # Shortcuts group
        group = Adw.PreferencesGroup()
        group.set_title("Custom Shortcuts")
        group.set_description("Quick typing shortcuts")

        # Type Date toggle
        row = Adw.SwitchRow()
        row.set_title("Type Date")
        row.set_subtitle("Ctrl + Alt + . copies YYYY-MM-DD HH:MM:SS to clipboard")

        # Check if keybinding exists
        row.set_active(self.has_keybinding("ky-insert-date"))
        row.connect("notify::active", self.on_date_toggle)

        group.add(row)

        # Screenshot toggle
        ss_row = Adw.SwitchRow()
        ss_row.set_title("Screenshot")
        ss_row.set_subtitle("Super + Shift + S takes a screenshot (Windows-style)")
        ss_row.set_active("<Shift><Super>s" in
            Gio.Settings.new("org.gnome.shell.keybindings").get_strv("show-screenshot-ui"))
        ss_row.connect("notify::active", self.on_screenshot_toggle)
        group.add(ss_row)

        page.add(group)

        # Speech to Text group
        stt_group = Adw.PreferencesGroup()
        stt_group.set_title("Speech to Text")
        stt_group.set_description("Dictate into any window using Speech Note")

        # Install row
        stt_install_row = Adw.ActionRow()
        stt_install_row.set_title("Speech Note")
        stt_install_row.set_subtitle("Offline speech-to-text engine (Flatpak)")
        self.stt_install_btn = Gtk.Button(label="Installed" if self.is_speech_note_installed() else "Install")
        self.stt_install_btn.set_valign(Gtk.Align.CENTER)
        self.stt_install_btn.set_sensitive(not self.is_speech_note_installed())
        self.stt_install_btn.connect("clicked", self.on_speech_note_install)
        stt_install_row.add_suffix(self.stt_install_btn)
        stt_group.add(stt_install_row)

        # Speech Lock install row
        sl_install_row = Adw.ActionRow()
        sl_install_row.set_title("Speech Lock Script")
        sl_install_row.set_subtitle("Locks dictation to one window (requires xdotool, xclip)")
        self.sl_install_btn = Gtk.Button(label="Installed" if self.is_speech_lock_installed() else "Install")
        self.sl_install_btn.set_valign(Gtk.Align.CENTER)
        self.sl_install_btn.set_sensitive(not self.is_speech_lock_installed())
        self.sl_install_btn.connect("clicked", self.on_speech_lock_install)
        sl_install_row.add_suffix(self.sl_install_btn)
        stt_group.add(sl_install_row)

        # Speech Lock run button
        sl_run_row = Adw.ActionRow()
        sl_run_row.set_title("Run Speech Lock")
        sl_run_row.set_subtitle(
            "Opens a terminal. Click target window, then dictate "
            "in Speech Note (clipboard mode). Text auto-pastes into "
            "the locked window. X11 only."
        )
        self.sl_run_btn = Gtk.Button(label="Run")
        self.sl_run_btn.set_valign(Gtk.Align.CENTER)
        self.sl_run_btn.set_sensitive(self.is_speech_lock_installed())
        self.sl_run_btn.connect("clicked", self.on_speech_lock_run)
        sl_run_row.add_suffix(self.sl_run_btn)
        stt_group.add(sl_run_row)
        self.sl_run_row = sl_run_row

        page.add(stt_group)

        self.stack.add_titled(page, "keyboard", "Keyboard")

    def add_timers_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Timers")

        # === ALARM ===
        alarm_group = Adw.PreferencesGroup()
        alarm_group.set_title("Alarm")
        alarm_group.set_description("Set an alarm for a specific time")

        # Time picker row
        alarm_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        alarm_box.set_margin_top(10)
        alarm_box.set_margin_bottom(10)

        self.alarm_hour = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.alarm_hour.set_value(datetime.now().hour)
        self.alarm_hour.set_width_chars(2)

        alarm_box.append(Gtk.Label(label="Hour:"))
        alarm_box.append(self.alarm_hour)

        self.alarm_minute = Gtk.SpinButton.new_with_range(0, 59, 1)
        self.alarm_minute.set_value(0)
        self.alarm_minute.set_width_chars(2)

        alarm_box.append(Gtk.Label(label="Min:"))
        alarm_box.append(self.alarm_minute)

        self.alarm_toggle = Gtk.ToggleButton(label="Set Alarm")
        self.alarm_toggle.connect("toggled", self.on_alarm_toggle)
        alarm_box.append(self.alarm_toggle)

        self.alarm_status = Gtk.Label(label="No alarm set")
        self.alarm_status.set_hexpand(True)
        self.alarm_status.set_halign(Gtk.Align.END)
        alarm_box.append(self.alarm_status)

        alarm_group.add(alarm_box)
        page.add(alarm_group)

        # === COUNTDOWN TIMER ===
        countdown_group = Adw.PreferencesGroup()
        countdown_group.set_title("Countdown Timer")
        countdown_group.set_description("Count down from a set duration")

        countdown_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        countdown_box.set_margin_top(10)
        countdown_box.set_margin_bottom(10)

        self.countdown_hours = Gtk.SpinButton.new_with_range(0, 23, 1)
        self.countdown_hours.set_value(0)
        self.countdown_hours.set_width_chars(2)
        countdown_box.append(Gtk.Label(label="H:"))
        countdown_box.append(self.countdown_hours)

        self.countdown_minutes = Gtk.SpinButton.new_with_range(0, 59, 1)
        self.countdown_minutes.set_value(5)
        self.countdown_minutes.set_width_chars(2)
        countdown_box.append(Gtk.Label(label="M:"))
        countdown_box.append(self.countdown_minutes)

        self.countdown_seconds = Gtk.SpinButton.new_with_range(0, 59, 1)
        self.countdown_seconds.set_value(0)
        self.countdown_seconds.set_width_chars(2)
        countdown_box.append(Gtk.Label(label="S:"))
        countdown_box.append(self.countdown_seconds)

        countdown_group.add(countdown_box)

        countdown_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        countdown_controls.set_margin_bottom(10)

        self.countdown_start_btn = Gtk.Button(label="Start")
        self.countdown_start_btn.connect("clicked", self.on_countdown_start)
        countdown_controls.append(self.countdown_start_btn)

        self.countdown_stop_btn = Gtk.Button(label="Stop")
        self.countdown_stop_btn.connect("clicked", self.on_countdown_stop)
        self.countdown_stop_btn.set_sensitive(False)
        countdown_controls.append(self.countdown_stop_btn)

        self.countdown_reset_btn = Gtk.Button(label="Reset")
        self.countdown_reset_btn.connect("clicked", self.on_countdown_reset)
        countdown_controls.append(self.countdown_reset_btn)

        self.countdown_display = Gtk.Label(label="00:00:00")
        self.countdown_display.add_css_class("title-1")
        self.countdown_display.set_hexpand(True)
        self.countdown_display.set_halign(Gtk.Align.END)
        countdown_controls.append(self.countdown_display)

        countdown_group.add(countdown_controls)
        page.add(countdown_group)

        # === STOPWATCH ===
        stopwatch_group = Adw.PreferencesGroup()
        stopwatch_group.set_title("Stopwatch")
        stopwatch_group.set_description("Track elapsed time")

        stopwatch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        stopwatch_box.set_margin_top(10)
        stopwatch_box.set_margin_bottom(10)

        self.stopwatch_start_btn = Gtk.Button(label="Start")
        self.stopwatch_start_btn.connect("clicked", self.on_stopwatch_start)
        stopwatch_box.append(self.stopwatch_start_btn)

        self.stopwatch_stop_btn = Gtk.Button(label="Stop")
        self.stopwatch_stop_btn.connect("clicked", self.on_stopwatch_stop)
        self.stopwatch_stop_btn.set_sensitive(False)
        stopwatch_box.append(self.stopwatch_stop_btn)

        self.stopwatch_reset_btn = Gtk.Button(label="Reset")
        self.stopwatch_reset_btn.connect("clicked", self.on_stopwatch_reset)
        stopwatch_box.append(self.stopwatch_reset_btn)

        self.stopwatch_display = Gtk.Label(label="00:00:00.0")
        self.stopwatch_display.add_css_class("title-1")
        self.stopwatch_display.set_hexpand(True)
        self.stopwatch_display.set_halign(Gtk.Align.END)
        stopwatch_box.append(self.stopwatch_display)

        stopwatch_group.add(stopwatch_box)
        page.add(stopwatch_group)

        self.stack.add_titled(page, "timers", "Timers")

    # === ALARM FUNCTIONS ===
    def on_alarm_toggle(self, button):
        if button.get_active():
            hour = int(self.alarm_hour.get_value())
            minute = int(self.alarm_minute.get_value())
            now = datetime.now()
            self.alarm_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if self.alarm_time <= now:
                self.alarm_time += timedelta(days=1)

            self.alarm_enabled = True
            self.alarm_status.set_label(f"Alarm: {self.alarm_time.strftime('%H:%M')}")
            button.set_label("Cancel")
            self.alarm_timer_id = GLib.timeout_add(1000, self.check_alarm)
        else:
            self.alarm_enabled = False
            if self.alarm_timer_id:
                GLib.source_remove(self.alarm_timer_id)
                self.alarm_timer_id = None
            self.alarm_status.set_label("No alarm set")
            button.set_label("Set Alarm")

    def check_alarm(self):
        if not self.alarm_enabled:
            return False
        if datetime.now() >= self.alarm_time:
            self.trigger_alarm()
            self.alarm_toggle.set_active(False)
            return False
        return True

    def trigger_alarm(self):
        """Play alarm sound and show notification."""
        subprocess.Popen(["pw-play", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"])
        subprocess.Popen(["notify-send", "-u", "critical", "Alarm", "Time's up!"])

    # === COUNTDOWN FUNCTIONS ===
    def on_countdown_start(self, button):
        if not self.countdown_running:
            if self.countdown_remaining.total_seconds() == 0:
                h = int(self.countdown_hours.get_value())
                m = int(self.countdown_minutes.get_value())
                s = int(self.countdown_seconds.get_value())
                self.countdown_remaining = timedelta(hours=h, minutes=m, seconds=s)

            if self.countdown_remaining.total_seconds() > 0:
                self.countdown_running = True
                self.countdown_start_btn.set_sensitive(False)
                self.countdown_stop_btn.set_sensitive(True)
                self.countdown_timer_id = GLib.timeout_add(100, self.update_countdown)

    def on_countdown_stop(self, button):
        self.countdown_running = False
        if self.countdown_timer_id:
            GLib.source_remove(self.countdown_timer_id)
            self.countdown_timer_id = None
        self.countdown_start_btn.set_sensitive(True)
        self.countdown_stop_btn.set_sensitive(False)

    def on_countdown_reset(self, button):
        self.on_countdown_stop(button)
        self.countdown_remaining = timedelta()
        self.countdown_display.set_label("00:00:00")

    def update_countdown(self):
        if not self.countdown_running:
            return False

        self.countdown_remaining -= timedelta(milliseconds=100)
        if self.countdown_remaining.total_seconds() <= 0:
            self.countdown_remaining = timedelta()
            self.countdown_display.set_label("00:00:00")
            self.on_countdown_stop(None)
            self.trigger_alarm()
            return False

        total = int(self.countdown_remaining.total_seconds())
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        self.countdown_display.set_label(f"{h:02d}:{m:02d}:{s:02d}")
        return True

    # === STOPWATCH FUNCTIONS ===
    def on_stopwatch_start(self, button):
        if not self.stopwatch_running:
            self.stopwatch_running = True
            self.stopwatch_start = datetime.now()
            self.stopwatch_start_btn.set_sensitive(False)
            self.stopwatch_stop_btn.set_sensitive(True)
            self.stopwatch_timer_id = GLib.timeout_add(100, self.update_stopwatch)

    def on_stopwatch_stop(self, button):
        if self.stopwatch_running:
            self.stopwatch_running = False
            self.stopwatch_elapsed += datetime.now() - self.stopwatch_start
            if self.stopwatch_timer_id:
                GLib.source_remove(self.stopwatch_timer_id)
                self.stopwatch_timer_id = None
            self.stopwatch_start_btn.set_sensitive(True)
            self.stopwatch_stop_btn.set_sensitive(False)

    def on_stopwatch_reset(self, button):
        self.on_stopwatch_stop(button)
        self.stopwatch_elapsed = timedelta()
        self.stopwatch_display.set_label("00:00:00.0")

    def update_stopwatch(self):
        if not self.stopwatch_running:
            return False

        elapsed = self.stopwatch_elapsed + (datetime.now() - self.stopwatch_start)
        total = elapsed.total_seconds()
        h, rem = divmod(int(total), 3600)
        m, s = divmod(rem, 60)
        tenths = int((total - int(total)) * 10)
        self.stopwatch_display.set_label(f"{h:02d}:{m:02d}:{s:02d}.{tenths}")
        return True

    def get_custom_keybindings(self):
        """Get list of custom keybinding paths."""
        settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
        return list(settings.get_strv("custom-keybindings"))

    def has_keybinding(self, name):
        """Check if a keybinding with this name exists."""
        for path in self.get_custom_keybindings():
            try:
                kb = Gio.Settings.new_with_path(KEYBINDING_SCHEMA, path)
                if kb.get_string("name") == name:
                    return True
            except:
                pass
        return False

    def add_keybinding(self, name, command, binding):
        """Add a custom keybinding."""
        settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
        paths = self.get_custom_keybindings()

        # Find next available slot
        i = 0
        while f"{KEYBINDING_PATH}/custom{i}/" in paths:
            i += 1
        new_path = f"{KEYBINDING_PATH}/custom{i}/"

        # Add to list
        paths.append(new_path)
        settings.set_strv("custom-keybindings", paths)

        # Configure the keybinding
        kb = Gio.Settings.new_with_path(KEYBINDING_SCHEMA, new_path)
        kb.set_string("name", name)
        kb.set_string("command", command)
        kb.set_string("binding", binding)

    def remove_keybinding(self, name):
        """Remove a keybinding by name."""
        settings = Gio.Settings.new("org.gnome.settings-daemon.plugins.media-keys")
        paths = self.get_custom_keybindings()
        new_paths = []

        for path in paths:
            try:
                kb = Gio.Settings.new_with_path(KEYBINDING_SCHEMA, path)
                if kb.get_string("name") != name:
                    new_paths.append(path)
                else:
                    # Reset the keybinding
                    kb.reset("name")
                    kb.reset("command")
                    kb.reset("binding")
            except:
                new_paths.append(path)

        settings.set_strv("custom-keybindings", new_paths)

    def on_date_toggle(self, row, _):
        if row.get_active():
            self.add_keybinding(
                "ky-insert-date",
                "bash -c 'wl-copy \"$(date +\"%F %T\")\"'",
                "<Control><Alt>period"
            )
        else:
            self.remove_keybinding("ky-insert-date")

    def on_screenshot_toggle(self, row, _):
        settings = Gio.Settings.new("org.gnome.shell.keybindings")
        bindings = settings.get_strv("show-screenshot-ui")
        if row.get_active():
            if "<Shift><Super>s" not in bindings:
                bindings.append("<Shift><Super>s")
                settings.set_strv("show-screenshot-ui", bindings)
        else:
            if "<Shift><Super>s" in bindings:
                bindings.remove("<Shift><Super>s")
                settings.set_strv("show-screenshot-ui", bindings)

    # === SPEECH TO TEXT FUNCTIONS ===
    def is_speech_note_installed(self):
        """Check if Speech Note is installed via Flatpak."""
        try:
            result = subprocess.run(
                ["flatpak", "list", "--app", "--columns=application"],
                capture_output=True, text=True, timeout=5
            )
            return "net.mkiol.SpeechNote" in result.stdout
        except:
            return False

    def on_speech_note_install(self, button):
        """Install Speech Note via Flatpak."""
        button.set_sensitive(False)
        button.set_label("Installing...")
        subprocess.Popen(
            ["flatpak", "install", "-y", "flathub", "net.mkiol.SpeechNote"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        GLib.timeout_add(30000, self._speech_note_install_done)

    def _speech_note_install_done(self):
        if self.is_speech_note_installed():
            self.stt_install_btn.set_label("Installed")
        else:
            self.stt_install_btn.set_label("Install")
            self.stt_install_btn.set_sensitive(True)
        return False

    # === SPEECH LOCK FUNCTIONS ===
    def is_speech_lock_installed(self):
        """Check if speech-lock script and deps are installed."""
        script = os.path.expanduser("~/.local/bin/speech-lock")
        return os.path.exists(script)

    def on_speech_lock_install(self, button):
        """Install speech-lock script and dependencies (xdotool, xclip)."""
        button.set_sensitive(False)
        button.set_label("Installing...")

        # Install xdotool and xclip if missing
        deps_needed = []
        for cmd in ["xdotool", "xclip"]:
            if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
                deps_needed.append(cmd)
        if deps_needed:
            subprocess.Popen(
                ["pkexec", "apt", "install", "-y"] + deps_needed,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Copy the script
        script_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "speech-lock")
        script_dst = os.path.expanduser("~/.local/bin/speech-lock")
        os.makedirs(os.path.dirname(script_dst), exist_ok=True)

        if os.path.exists(script_src):
            import shutil
            shutil.copy2(script_src, script_dst)
            os.chmod(script_dst, 0o755)

        GLib.timeout_add(5000, self._speech_lock_install_done)

    def _speech_lock_install_done(self):
        if self.is_speech_lock_installed():
            self.sl_install_btn.set_label("Installed")
            self.sl_run_btn.set_sensitive(True)
        else:
            self.sl_install_btn.set_label("Install")
            self.sl_install_btn.set_sensitive(True)
        return False

    def on_speech_lock_run(self, button):
        """Launch speech-lock in a terminal window."""
        script = os.path.expanduser("~/.local/bin/speech-lock")
        subprocess.Popen(
            ["gnome-terminal", "--title=Speech Lock", "--", "python3", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def add_privacy_page(self):
        page = Adw.PreferencesPage()
        page.set_title("Privacy")
        page.set_icon_name("security-high-symbolic")

        # Cleanup group
        cleanup_group = Adw.PreferencesGroup()
        cleanup_group.set_title("Cleanup")
        cleanup_group.set_description("Manage temporary and old files")

        # Screenshot cleanup toggle
        ss_row = Adw.SwitchRow()
        ss_row.set_title("Auto-delete Screenshots")
        ss_row.set_subtitle("Delete screenshots older than 24 hours from Pictures/Screenshots")
        ss_row.set_active(self.is_ss_cleanup_enabled())
        ss_row.connect("notify::active", self.on_ss_cleanup_toggle)
        cleanup_group.add(ss_row)

        page.add(cleanup_group)
        self.stack.add_titled(page, "privacy", "Privacy")

    def is_ss_cleanup_enabled(self):
        """Check if screenshot cleanup is enabled."""
        return SS_CLEANUP_FLAG.exists()

    def on_ss_cleanup_toggle(self, row, _):
        """Enable or disable screenshot cleanup."""
        if self._initializing:
            return
        if row.get_active():
            SS_CLEANUP_FLAG.touch()
            # Run cleanup immediately
            self.cleanup_screenshots_loop()
        else:
            if SS_CLEANUP_FLAG.exists():
                SS_CLEANUP_FLAG.unlink()

    def cleanup_screenshots_loop(self):
        """Background loop to delete old screenshots."""
        if not self.is_ss_cleanup_enabled():
            return True # Keep the timer running

        ss_dir = pathlib.Path.home() / "Pictures" / "Screenshots"
        if not ss_dir.exists():
            return True

        now = datetime.now()
        cutoff = now - timedelta(hours=24)

        try:
            for file in ss_dir.glob("Screenshot from *.png"):
                if file.is_file():
                    mtime = datetime.fromtimestamp(file.stat().st_mtime)
                    if mtime < cutoff:
                        print(f"Deleting old screenshot: {file}")
                        file.unlink()
        except Exception as e:
            print(f"Error during screenshot cleanup: {e}")

        return True # Keep the timer running

KySettings().run(None)
