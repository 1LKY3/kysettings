# KySettings

Personal GNOME settings app built with GTK 4 and Libadwaita. Extends Ubuntu's default Settings with stuff I actually need.

## Install

```bash
git clone https://github.com/1LKY3/kysettings.git
cd kysettings
./install.sh
```

The installer checks for dependencies (`python3-gi`, `gir1.2-adw-1`) and installs them if missing.

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

## Features

**Display**
- Extended screen blank timeout (up to 4 hours)
- Pin to dash toggle
- Minecraft auto-mute — automatically mutes the standard Linux Minecraft installation (Java Edition) when the window loses focus

**Wireless**
- Bluetooth power toggle and adapter reset
- PDANet+ transparent proxy (routes all TCP through USB tether via redsocks)

**Keyboard**
- Type Date shortcut (Ctrl+Alt+. inserts current date/time)

**Timers**
- Alarm clock
- Countdown timer
- Stopwatch

## Requirements

- Ubuntu 22.04+ (or any distro with GTK 4 / Libadwaita)
- Python 3.10+
- `python3-gi`, `gir1.2-adw-1`
