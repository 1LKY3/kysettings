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
            self.pin_to_dash()
            self.show_welcome()
            FIRST_RUN_FLAG.parent.mkdir(parents=True, exist_ok=True)
            FIRST_RUN_FLAG.touch()

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
         "file:///usr/share/backgrounds/Fuji_san_by_amaral.png",
         "file:///usr/share/backgrounds/ubuntu-wallpaper-d.png"),
        ("org.gnome.desktop.background", "picture-uri",
         "file:///usr/share/backgrounds/Fuji_san_by_amaral.png",
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
        page.set_icon_name("video-display-symbolic")
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

        # Minecraft auto-mute install row
        mc_install_row = Adw.ActionRow()
        mc_install_row.set_title("Minecraft Auto-Mute Script")
        mc_install_row.set_subtitle("For standard Minecraft Java Edition on Linux")
        self.mc_install_btn = Gtk.Button(label="Installed" if self.is_mc_mute_installed() else "Install")
        self.mc_install_btn.set_valign(Gtk.Align.CENTER)
        self.mc_install_btn.set_sensitive(not self.is_mc_mute_installed())
        self.mc_install_btn.connect("clicked", self.on_mc_mute_install)
        mc_install_row.add_suffix(self.mc_install_btn)
        audio_group.add(mc_install_row)

        # Minecraft auto-mute toggle
        mc_mute_row = Adw.SwitchRow()
        mc_mute_row.set_title("Minecraft Auto-Mute")
        mc_mute_row.set_subtitle("Mute Minecraft Java Edition when window loses focus")
        mc_mute_row.set_active(self.is_minecraft_mute_running())
        mc_mute_row.set_sensitive(self.is_mc_mute_installed())
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

    def is_mc_mute_installed(self):
        """Check if minecraft-auto-mute script and deps are installed."""
        script = os.path.expanduser("~/.local/bin/minecraft-auto-mute.sh")
        return os.path.exists(script)

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

    def on_mc_mute_install(self, button):
        """Install minecraft-auto-mute script and dependencies."""
        button.set_sensitive(False)
        button.set_label("Installing...")

        # Install xdotool if missing
        try:
            subprocess.run(["which", "xdotool"], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            subprocess.Popen(
                ["pkexec", "apt", "install", "-y", "xdotool"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Write the script
        script_path = os.path.expanduser("~/.local/bin/minecraft-auto-mute.sh")
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        script_content = '''#!/bin/bash
# Auto-mute Minecraft when window loses focus
# Uses PipeWire (wpctl) and xdotool for window monitoring

MINECRAFT_MUTED=false

get_minecraft_stream_id() {
    wpctl status | sed -n '/Streams:/,/^$/p' | grep -E "^\\s+[0-9]+\\. java" | head -1 | awk '{print $1}' | tr -d '.'
}

mute_minecraft() {
    local stream_id=$(get_minecraft_stream_id)
    if [[ -n "$stream_id" && "$MINECRAFT_MUTED" == "false" ]]; then
        wpctl set-mute "$stream_id" 1
        MINECRAFT_MUTED=true
    fi
}

unmute_minecraft() {
    local stream_id=$(get_minecraft_stream_id)
    if [[ -n "$stream_id" && "$MINECRAFT_MUTED" == "true" ]]; then
        wpctl set-mute "$stream_id" 0
        MINECRAFT_MUTED=false
    fi
}

is_minecraft_focused() {
    local active_window=$(xdotool getactivewindow 2>/dev/null)
    if [[ -z "$active_window" ]]; then
        return 1
    fi
    local window_class=$(xprop -id "$active_window" WM_CLASS 2>/dev/null | grep -i minecraft)
    local window_name=$(xdotool getwindowname "$active_window" 2>/dev/null)
    if [[ -n "$window_class" ]] || [[ "$window_name" == *"Minecraft"* ]]; then
        return 0
    fi
    return 1
}

if is_minecraft_focused; then
    MINECRAFT_MUTED=false
else
    mute_minecraft
fi

xprop -root -spy _NET_ACTIVE_WINDOW 2>/dev/null | while read -r line; do
    if is_minecraft_focused; then
        unmute_minecraft
    else
        mute_minecraft
    fi
done
'''
        with open(script_path, 'w') as f:
            f.write(script_content)
        os.chmod(script_path, 0o755)

        GLib.timeout_add(3000, self._mc_mute_install_done)

    def _mc_mute_install_done(self):
        if self.is_mc_mute_installed():
            self.mc_install_btn.set_label("Installed")
            self.mc_mute_row.set_sensitive(True)
        else:
            self.mc_install_btn.set_label("Install")
            self.mc_install_btn.set_sensitive(True)
        return False

    def on_minecraft_mute_toggle(self, row, _):
        """Start or stop the Minecraft auto-mute script."""
        if self._initializing:
            return
        script_path = os.path.expanduser("~/.local/bin/minecraft-auto-mute.sh")

        if row.get_active():
            subprocess.Popen(
                [script_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
        else:
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

KySettings().run(None)
