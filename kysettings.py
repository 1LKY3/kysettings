#!/usr/bin/env python3
"""KySettings - Custom GNOME Settings"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib
import subprocess
import os
import pathlib
from datetime import datetime, timedelta

FIRST_RUN_FLAG = pathlib.Path.home() / ".config" / "kysettings" / ".installed"

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

    def on_activate(self, app):
        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_title("Ky Settings")
        self.win.set_default_size(500, 500)

        # Main layout
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        box.append(header)

        # Stack for multiple pages
        self.stack = Adw.ViewStack()

        # Add pages
        self.add_display_page()
        self.add_wireless_page()
        self.add_keyboard_page()
        self.add_timers_page()

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
            self.show_welcome()
            FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
            FIRST_RUN_FLAG.touch()

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

    def add_display_page(self):
        page = Adw.PreferencesPage()
        page.set_icon_name("video-display-symbolic")
        page.set_title("Display")

        # Screen Blank group
        group = Adw.PreferencesGroup()
        group.set_title("Screen Blank")
        group.set_description("Extended timeout options")

        row = Adw.ComboRow()
        row.set_title("Blank Screen After")

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

        # Minecraft auto-mute toggle
        mc_mute_row = Adw.SwitchRow()
        mc_mute_row.set_title("Minecraft Auto-Mute")
        mc_mute_row.set_subtitle("Mute Minecraft when window loses focus")
        mc_mute_row.set_active(self.is_minecraft_mute_running())
        mc_mute_row.connect("notify::active", self.on_minecraft_mute_toggle)
        audio_group.add(mc_mute_row)
        self.mc_mute_row = mc_mute_row

        page.add(audio_group)

        self.stack.add_titled(page, "display", "Display")

    def is_pinned_to_dash(self):
        """Check if app is in GNOME favorites."""
        try:
            settings = Gio.Settings.new("org.gnome.shell")
            favorites = settings.get_strv("favorite-apps")
            return "kysettings.desktop" in favorites
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
                if "kysettings.desktop" not in favorites:
                    favorites.append("kysettings.desktop")
            else:
                if "kysettings.desktop" in favorites:
                    favorites.remove("kysettings.desktop")

            settings.set_strv("favorite-apps", favorites)
        except Exception as e:
            print(f"Error toggling pin: {e}")

    def is_minecraft_mute_running(self):
        """Check if minecraft-auto-mute.sh is running."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "minecraft-auto-mute"],
                capture_output=True
            )
            return result.returncode == 0
        except:
            return False

    def on_minecraft_mute_toggle(self, row, _):
        """Start or stop the Minecraft auto-mute script."""
        if self._initializing:
            return
        script_path = os.path.expanduser("~/.local/bin/minecraft-auto-mute.sh")

        if row.get_active():
            # Start the script
            if os.path.exists(script_path):
                subprocess.Popen(
                    [script_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            else:
                row.set_active(False)
                dialog = Adw.MessageDialog(
                    transient_for=self.win,
                    heading="Script Not Found",
                    body=f"Minecraft auto-mute script not found at:\n{script_path}"
                )
                dialog.add_response("ok", "OK")
                dialog.present()
        else:
            # Stop the script
            subprocess.run(["pkill", "-f", "minecraft-auto-mute"], capture_output=True)

    def add_wireless_page(self):
        page = Adw.PreferencesPage()
        page.set_icon_name("network-wireless-symbolic")
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
        pda_group.set_description("Route all traffic through PDANet+ USB tether")

        # Install row
        pda_install_row = Adw.ActionRow()
        pda_install_row.set_title("Install redsocks")
        pda_install_row.set_subtitle("Required for transparent proxy redirect")
        self.pda_install_btn = Gtk.Button(label="Installed" if self.is_redsocks_installed() else "Install")
        self.pda_install_btn.set_valign(Gtk.Align.CENTER)
        self.pda_install_btn.set_sensitive(not self.is_redsocks_installed())
        self.pda_install_btn.connect("clicked", self.on_pdanet_install)
        pda_install_row.add_suffix(self.pda_install_btn)
        pda_group.add(pda_install_row)

        # Proxy toggle
        pda_toggle_row = Adw.SwitchRow()
        pda_toggle_row.set_title("PDANet+ Proxy")
        pda_toggle_row.set_subtitle("192.168.49.1:8000 — all traffic via tether")
        pda_toggle_row.set_active(self.is_pdanet_proxy_running())
        pda_toggle_row.set_sensitive(self.is_redsocks_installed())
        pda_toggle_row.connect("notify::active", self.on_pdanet_proxy_toggle)
        pda_group.add(pda_toggle_row)
        self.pda_toggle_row = pda_toggle_row

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
        subprocess.Popen(
            ["pkexec", os.path.expanduser("~/.local/bin/bt-reset")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Re-enable button and refresh state after sequence completes (~15s)
        GLib.timeout_add(16000, self._bluetooth_reset_done, button)

    def _bluetooth_reset_done(self, button):
        button.set_sensitive(True)
        button.set_label("Reset")
        self._bluetooth_refresh_state()
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

    def is_pdanet_proxy_running(self):
        """Check if the PDANet+ proxy is currently active."""
        try:
            result = subprocess.run(
                ["pkexec", os.path.expanduser("~/.local/bin/pdanet-proxy"), "status"],
                capture_output=True, text=True, timeout=5
            )
            return "running" in result.stdout
        except:
            return False

    def on_pdanet_install(self, button):
        """Install redsocks via apt."""
        button.set_sensitive(False)
        button.set_label("Installing...")
        subprocess.Popen(
            ["pkexec", "apt", "install", "-y", "redsocks"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Check after 10 seconds if install finished
        GLib.timeout_add(10000, self._pdanet_install_done)

    def _pdanet_install_done(self):
        if self.is_redsocks_installed():
            self.pda_install_btn.set_label("Installed")
            self.pda_toggle_row.set_sensitive(True)
        else:
            self.pda_install_btn.set_label("Install")
            self.pda_install_btn.set_sensitive(True)
        return False

    def on_pdanet_proxy_toggle(self, row, _):
        """Start or stop the PDANet+ transparent proxy."""
        if self._initializing:
            return
        if row.get_active():
            subprocess.Popen(
                ["pkexec", os.path.expanduser("~/.local/bin/pdanet-proxy"), "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["pkexec", os.path.expanduser("~/.local/bin/pdanet-proxy"), "stop"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def on_blank_changed(self, row, _):
        _, seconds = self.blank_options[row.get_selected()]
        Gio.Settings.new("org.gnome.desktop.session").set_uint("idle-delay", seconds)

    def add_keyboard_page(self):
        page = Adw.PreferencesPage()
        page.set_icon_name("input-keyboard-symbolic")
        page.set_title("Keyboard")

        # Shortcuts group
        group = Adw.PreferencesGroup()
        group.set_title("Custom Shortcuts")
        group.set_description("Quick typing shortcuts")

        # Type Date toggle
        row = Adw.SwitchRow()
        row.set_title("Type Date")
        row.set_subtitle("Ctrl + Alt + . inserts YYYY-MM-DD HH:MM:SS")

        # Check if keybinding exists
        row.set_active(self.has_keybinding("ky-insert-date"))
        row.connect("notify::active", self.on_date_toggle)

        group.add(row)
        page.add(group)

        self.stack.add_titled(page, "keyboard", "Keyboard")

    def add_timers_page(self):
        page = Adw.PreferencesPage()
        page.set_icon_name("alarm-symbolic")
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
            # Check if xdotool is installed
            try:
                subprocess.run(["which", "xdotool"], check=True, capture_output=True)
            except subprocess.CalledProcessError:
                row.set_active(False)
                dialog = Adw.MessageDialog(
                    transient_for=self.win,
                    heading="Missing Dependency",
                    body="Please install xdotool:\nsudo apt install xdotool"
                )
                dialog.add_response("ok", "OK")
                dialog.present()
                return

            self.add_keybinding(
                "ky-insert-date",
                'bash -c "sleep 0.2 && xdotool type --clearmodifiers \\"$(date +\'%F %T\')\\""',
                "<Control><Alt>period"
            )
        else:
            self.remove_keybinding("ky-insert-date")

KySettings().run(None)
