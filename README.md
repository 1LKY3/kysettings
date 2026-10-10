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
- `python3-nautilus` — Nautilus Python bindings (used by the Files extensions)
- `redsocks` — Transparent TCP proxy redirector (used by PDANet transparent proxy)

To remove them manually if no longer needed:
```bash
sudo apt remove python3-gi gir1.2-adw-1 python3-nautilus redsocks
```

## Features

**PC** (0.5.2, the first tab and the one Ky Settings opens on)
- Two columns: everything about RAM on the left (effective RAM card, Tune, quick
  actions, where memory is, memory history, zram, swap areas); GPU first, then CPU and network
  on the right. `KYSETTINGS_PAGE=pc KYSETTINGS_MAXIMIZED=1 kysettings` opens straight on it.
- **Effective RAM is the headline:** one big number for everything the PC can
  hold (RAM, then compressed RAM, then SSD swap), free space right now, how many
  times the physical RAM that works out to, and a speed-zone bar showing how full
  each zone is.
- **Tune:** swap eagerness (swappiness 10 to 180), compressed RAM size (zram, up to
  1.5x RAM), compression (zstd, lz4, lzo-rle) and the SSD swap file size, with a live
  "after applying" preview and Restore recommended (100, 16 GB zstd, 48 GB).
  Changes go through `ky-memory` with one password prompt. As root it re-checks
  everything: values in range, data moved out of zram or a swap file must fit in
  free RAM plus other swap with a 2 GB margin, a swap file leaves 50 GB free on its
  ext4 drive, and swap grows before anything shrinks. Original files are kept as
  `.ky-orig`. If zram-tools is missing, an Install button offers it.
- **Quick actions:** free up file cache, and move SSD swap back into RAM (only
  offered when it fits with room to spare).
- **GPU** (AMD cards on amdgpu): usage, video memory and power graph; temperatures,
  fan, clocks, video memory spilled into system RAM, PCIe link; video memory by app
  (refreshed every 3 seconds in the background, with a warning past 92 % full).
  **Tune GPU** offers only what the driver manages itself: performance (automatic,
  quiet, full speed), workload profile (Default, Gaming, Power saving, Video, VR,
  Compute) and a power limit inside the driver's own range. No overclocking,
  undervolting or manual fan control. Changes go through `ky-gpu` with one password
  prompt; non-default settings come back after a restart through a root-owned
  `/usr/local/sbin/ky-gpu-restore` with the values baked in (`ky-gpu.service`).
  Restore defaults removes both.
- Live one-minute graphs in the style of Ubuntu's System Monitor for memory and
  swap, all CPU threads and network; samples once a second, draws only while open.

**Display**
- Use LXTerminal as Default — switches Ubuntu's system terminal alternative,
  GNOME terminal preference (including Ctrl+Alt+T and desktop folder actions),
  Files’ Open in Terminal menu, and KySettings Speech Lock. Requires LXTerminal
  installed and administrator authentication. First enable installs
  `xdg-terminal-exec` for terminal-based apps; `./install.sh` installs
  `python3-nautilus` for the Files extensions. These shared dependencies remain
  on OFF. A permanent XDG desktop entry
  delegates to Ubuntu’s terminal alternative; OFF restores the previous XDG
  configuration files as well as the terminal choice.
  Close Files windows and reopen Files after switching to reload extensions.
  GNOME Terminal remains installed. OFF restores the prior automatic/manual
  alternative and exact GNOME user values; uninstall restores them first.
  The system alternative and Files integration apply to all users.
  Recovery snapshots: `~/.config/kysettings/terminal-before.json` and
  `/var/lib/kysettings/terminal-before.json`. The GNOME Terminal Files extension
  is preserved using `dpkg-divert`, including across package updates.
  Apps explicitly configured to run another terminal retain their own settings.
  CLI: `ky-terminal enable|disable|status`.
- Workspace Monitor — opens the same target-monitor menu as the dock launcher.
  Ctrl+Alt+Left/Right controls the selected display while the primary display,
  panel, and dock stay in place. Requires the Workspace Monitor MVP extension
  (a locally patched CHC-E build, currently tested on GNOME 46). If the extension
  is not loaded, the launcher explains the required setup instead of opening
  primary-display settings.
- Kyle's Desktop — a complete, versioned preset with Applied, Customized,
  Incomplete, and Not applied status; Reapply preserves the original baseline
- Bundled K1/K2 Voidflow wallpaper, applied by Kyle's Desktop
- Minimize and Maximize title-bar buttons, applied by Kyle's Desktop
- Extended screen blank timeout (up to 4 hours)
- Pin to dash toggle
- Window size is remembered between launches
- Game auto-mute — mutes any running game while its window is not focused, and unmutes it when you come back
- Wayland Focus (experimental) — extends game auto-mute to Wayland-native games
- Minimize on Right-Click — adds a **Minimize** entry to the dock's app icon right-click menu
- Copy Path on Right-Click — adds **Copy Path** to Files' right-click menus for pictures,
  files, folders, and folder backgrounds

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

**Copy Path on Right-Click**

Adds a **Copy Path** entry — **Copy N Paths** for a multi-selection — to Files'
right-click menus for pictures, files, and folders, and to the folder-background
menu, where it copies the current folder's path. The clipboard is written with
`wl-copy` on Wayland and `xclip` on X11.

The extension ships with `./install.sh` but stays inert until the toggle creates
`~/.config/kysettings/copy-path.enabled`. Because the flag is read every time a
menu opens, switching the toggle applies to already-open Files windows; only the
first enable after installation needs Files reopened if it was already running.
OFF deletes the flag and leaves the extension loaded but inert.

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
- Keychron Super Key — maps left Super to right Super on the USB Keychron K4
  (05ac:024f), so the Windows key can share the mouse's overview shortcut.
  Enable when GNOME's overview key is `Super_R`. Uses administrator authentication;
  both on and off apply immediately and persist across reconnects and restarts.
  Detects the existing `/etc/udev/hwdb.d/90-keychron-super.hwdb` fix. Turning it
  off restores left Super without changing the mouse or GNOME's overview binding.
  Uninstalling the app keeps this preference; turn it off first to remove the remap.
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

Kyle's Desktop saves the previous state before changing settings. The complete
preset includes the existing sage appearance and Voidflow wallpaper, 40px dock
icons, and these choices:

| On | Off / selected value |
| --- | --- |
| LXTerminal as default | Hide Top Bar off |
| Cycle Monitors with Keyboard | All Displays Together off |
| Pin KySettings to Dash | Wayland Focus off |
| Game Auto-Mute | Window, top-bar, and overview blur off |
| Minimize on Right-Click | PDANet and transparent proxy off |
| Keychron Super Key | Monitor timeout Never |
| Type Date and Screenshot shortcuts | |
| Auto-delete Screenshots | |
| Bluetooth, when an adapter is present | |

Individual controls remain available after applying. The status compares real
settings, services, and extension availability; a matching theme alone is never
proof that the preset was applied. **Customized** means an applied preset now
has differing settings. **Incomplete** means an operation failed, a required
component is unavailable, or an extension is pending activation. **Reapply**
reasserts the preset without replacing the original restoration snapshot.
Status refreshes after control changes and when the window gains focus; there
is no resident preset helper or polling loop.

`~/.config/kysettings/desktop-before-kyle.json` contains exact typed GNOME user
values (including inherited defaults), relevant files, and previous helper
states. `desktop-preset.json` tracks application/restoration progress. Files are
written atomically with mode 0600. An interrupted or unsuccessful operation keeps
its recovery data, and OFF can be retried. Old version-1 appearance snapshots
remain restorable; applying the expanded preset adds newly managed settings to
them without replacing the earlier values.

An existing customized desktop can use its current state as the baseline; the
app does not invent a historical pre-Kyle configuration. LXTerminal and the
Keychron mapping that were already enabled before applying remain enabled when
the desktop preset is restored. Terminal and keyboard system changes use their
existing helpers and administrator authentication. Missing required extensions
are reported for installation, followed by Reapply; extensions newly installed
on Wayland may require a new login. The Workspace Monitor extension is a
separate prerequisite described above.

Opening the Keyboard page does not enable screenshot shortcuts. Effects use
extension-local schemas when needed. Screenshot cleanup keeps its existing
behavior: it runs while KySettings is open, deleting matching screenshots older
than 24 hours; restoring the setting cannot recover already-deleted files.
Timers and alarms are runtime actions and are not started by the preset.

The uninstaller restores an active desktop snapshot before removing the engine.
If restoration fails, it retains the app and recovery data for retry.

For scripts or troubleshooting:

```sh
ky-desktop status   # JSON: actual preset status and differences
ky-desktop apply    # Apply or reapply, preserving the original snapshot
ky-desktop restore  # Restore; retain snapshot if any step fails
```

Validation: `/usr/bin/python3 scripts/test_desktop.py` runs isolated lifecycle,
restoration, migration, file, shortcut, and cancellation tests without changing
the live desktop. `/usr/bin/python3 scripts/test_copy_path.py` covers the Files
Copy Path menu and clipboard selection the same way.

## Requirements

- Ubuntu 22.04+ (or any distro with GTK 4 / Libadwaita)
- Python 3.10+
- Dependencies installed automatically by `./install.sh`

Workspace Monitor also has a **Cycle Monitors with Keyboard** toggle in
Display → Workspaces. When enabled, Ctrl+Alt+Up/Down chooses the target display
and Ctrl+Alt+Left/Right switches its workspace.
