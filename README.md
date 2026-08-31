# KySettings

Personal GNOME settings app built with GTK 4 and Libadwaita. Extends Ubuntu's default Settings with stuff I actually need.

## Install

```bash
git clone https://github.com/1LKY3/kysettings.git
cd kysettings
./install.sh
```

The installer installs all dependencies automatically.

## Usage

Run from terminal:
```bash
kysettings
```

Or search **"Ky Settings"** in your app launcher.

## Uninstall

```bash
./uninstall.sh
```

This removes KySettings and all its helper scripts. It also cleans up any active PDANet proxy settings and the apt proxy config.

The following system packages are installed by `./install.sh` but are **not removed** by the uninstaller (they may be used by other programs):

- `python3` — Python interpreter
- `python3-gi` — Python GObject Introspection bindings
- `gir1.2-adw-1` — Libadwaita typelib for GTK 4
- `redsocks` — Transparent TCP proxy redirector (used by PDANet transparent proxy)

To remove them manually if no longer needed:
```bash
sudo apt remove python3-gi gir1.2-adw-1 redsocks
```

## Features

**Display**
- Kyle's Desktop toggle — ON snapshots and applies the theme/font/dock set;
  OFF restores the exact per-user state captured before ON
- Bundled K1/K2 Voidflow wallpaper, applied by Kyle's Desktop
- Minimize and Maximize title-bar buttons, applied by Kyle's Desktop
- Extended screen blank timeout (up to 4 hours)
- Pin to dash toggle
- Window size is remembered between launches
- Game auto-mute — mutes any running game while its window is not focused, and unmutes it when you come back
- Wayland Focus (experimental) — extends game auto-mute to Wayland-native games
- Minimize on Right-Click — adds a **Minimize** entry to the dock's app icon right-click menu

**Minimize on Right-Click**

Ships a small GNOME Shell extension (`dash-minimize@ky.local`) that adds a Minimize
item between the window list and Quit in the dock's right-click menu. It minimizes
every window the app has on the current workspace, including fullscreen Proton/Wine
games, so a game running borderless can be dropped to the dock without alt-tabbing.

The dock (Ubuntu Dock / Dash to Dock) does not export the class that builds that
menu, so the extension briefly wraps `PopupMenu.open` to catch the first dock menu,
takes the class from that instance, and unwraps itself again.

`./install.sh` copies the extension into `~/.local/share/gnome-shell/extensions/`.
GNOME Shell only scans for new extensions when a session starts, so the first time
the toggle is switched on a **Finish Enabling** row appears under it with a Log Out
button. A reboot works too, but nothing outside the session needs restarting — only
gnome-shell does, and it cannot be restarted in place on Wayland.

After that first login the extension is loaded and the toggle applies immediately,
in both directions. The toggle writes `org.gnome.shell enabled-extensions` rather
than shelling out to `gnome-extensions enable`, because that command refuses
extensions the running shell has not scanned yet.

Kyle's Desktop enables this extension automatically. The separate Dock switch is
still available as an override.

**Game auto-mute detection**

A PipeWire stream counts as a game if its process (or any ancestor) is a Steam/Proton
title, a Wine process, Minecraft, or a Lutris/Heroic/Bottles launch. Add your own
matches — one lowercase substring per line, matched against the process cmdline — in:

```
~/.config/kysettings/game-mute-markers.txt
```

Only streams the script muted itself are ever unmuted, so a manual mute is never
undone, and everything is restored when the toggle is switched off.

**Wayland Focus (experimental)**

Game auto-mute finds the focused window through `_NET_ACTIVE_WINDOW`, which only
X11 and Xwayland windows appear in. A Wayland-native window reports as `0x0`
there — indistinguishable from "nothing is focused" — so a focused Wayland-native
game looks unfocused and gets muted *while you are playing it*. Proton, Wine and
most launchers go through Xwayland, so the X11 path covers nearly everything;
native Vulkan/SDL3 and Godot titles are where it bites.

Wayland deliberately gives clients no way to ask which window has focus, and
GNOME's own `org.gnome.Shell.Introspect` refuses callers that aren't on its
allowlist, so the answer has to come from inside the shell. The
`ky-focus@ky.local` extension shipped here publishes just the focused window's
PID on the session bus, and the daemon asks it first when the experiment is on.

It is a **separate toggle beside Game Auto-Mute, not a replacement**. Off — the
default — is the X11 path unchanged, with no code in common. On, the daemon
prefers the shell and still falls back to X11 whenever the shell cannot answer,
so a missing or disabled extension degrades to the old behaviour rather than
breaking. The switch writes `~/.config/kysettings/wayland-focus.enabled`, enables
the extension, and restarts the daemon; the extension itself loads at the next
login like any other.

Leave it off until it has been proven on real Wayland-native games.

The Game Auto-Mute toggle also writes `~/.config/autostart/game-auto-mute.desktop`, so it stays
on across reboots. The daemon holds an flock on
`~/.config/kysettings/game-auto-mute.lock`; starting it twice is harmless, and
the switch reads that lock rather than a `pgrep` match (`pgrep -f` matches any
command line that merely mentions the script, which reported false positives).

**Wireless**
- Bluetooth power toggle and adapter reset
- PDANet+ Proxy — sets GNOME system proxy + shell env vars + apt config for WiFi tethering through PDANet+
- Transparent Proxy (redsocks) — routes ALL TCP traffic through PDANet+ via iptables for apps that ignore system proxy settings

**Keyboard**
- Type Date shortcut (Ctrl+Alt+. inserts current date/time)
- Speech to Text — install Speech Note (offline, via Flatpak)
- Speech Lock — lock dictation to a specific window. Opens a terminal, click your target window, then dictate in Speech Note (clipboard mode). Text auto-pastes into the locked window no matter what's focused. X11 only.

**Timers**
- Alarm clock
- Countdown timer
- Stopwatch

## CLI

PDANet proxy can also be toggled from the terminal:

```bash
pdanet on       # Enable system proxy (gsettings + env vars + apt)
pdanet off      # Disable and reset all settings
pdanet status   # Check current state
```

## Portability

Nothing is tied to one machine's home directory. Two details worth knowing if you
install this somewhere else:

- **Wallpaper.** The K1/K2 `voidflow-mountains.png` image ships with KySettings
  and is installed in `~/.local/share/backgrounds`. Kyle's Desktop applies it to
  both light and dark GNOME backgrounds.
- **Missing schemas are skipped, not fatal.** `Gio.Settings.new()` on a schema
  that isn't installed aborts the process — it is a GLib fatal error that no
  `try`/`except` can catch. Every non-stock schema is therefore looked up first,
  so a machine without dash-to-dock skips those keys and reports them instead of
  crashing.

Turning the toggle OFF does not reset or guess any values. KySettings stores
whether each key had an explicit user value and its typed GVariant value in
`~/.config/kysettings/desktop-before-kyle.json`. OFF restores those values and
removes the snapshot only after a successful restoration. Older installations
without a snapshot are left unchanged rather than being reset.

The uninstaller restores an active snapshot before removing KySettings. If any
captured setting cannot be restored, uninstalling stops and keeps both the app
and snapshot available for a safe retry.

## Requirements

- Ubuntu 22.04+ (or any distro with GTK 4 / Libadwaita)
- Python 3.10+
- Dependencies installed automatically by `./install.sh`
