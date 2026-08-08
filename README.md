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
- Extended screen blank timeout (up to 4 hours)
- Pin to dash toggle
- Window size is remembered between launches
- Game auto-mute — mutes any running game while its window is not focused, and unmutes it when you come back

**Game auto-mute detection**

A PipeWire stream counts as a game if its process (or any ancestor) is a Steam/Proton
title, a Wine process, Minecraft, or a Lutris/Heroic/Bottles launch. Add your own
matches — one lowercase substring per line, matched against the process cmdline — in:

```
~/.config/kysettings/game-mute-markers.txt
```

Only streams the script muted itself are ever unmuted, so a manual mute is never
undone, and everything is restored when the toggle is switched off.

The toggle also writes `~/.config/autostart/game-auto-mute.desktop`, so it stays
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

## Requirements

- Ubuntu 22.04+ (or any distro with GTK 4 / Libadwaita)
- Python 3.10+
- Dependencies installed automatically by `./install.sh`
