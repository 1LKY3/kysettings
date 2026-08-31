#!/bin/bash
set -e

echo "=== KySettings Installer ==="

# game-auto-mute exists twice: as scripts/game-auto-mute, and verbatim inside
# kysettings.py so the in-app Install button can write it without the repo.
# Refuse to install a build where the two have drifted apart.
python3 - <<'DRIFT' || exit 1
import pathlib, re, sys
app = pathlib.Path("kysettings.py").read_text()
script = pathlib.Path("scripts/game-auto-mute").read_text()
m = re.search(r"GAME_MUTE_SCRIPT_SOURCE = r'''(.*?)'''", app, re.S)
if not m:
    sys.exit("ERROR: GAME_MUTE_SCRIPT_SOURCE not found in kysettings.py")
if m.group(1) != script:
    sys.exit("ERROR: scripts/game-auto-mute and the copy embedded in "
             "kysettings.py have drifted apart. Re-sync them before installing.")
DRIFT

# All dependencies — install everything upfront so nothing needs internet later
ALL_DEPS=(python3 python3-gi gir1.2-adw-1 redsocks xdotool xclip wl-clipboard)
MISSING=()
for pkg in "${ALL_DEPS[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Installing dependencies: ${MISSING[*]}"
    sudo apt install -y "${MISSING[@]}"
fi

# Disable default redsocks service (we manage our own instance)
sudo systemctl stop redsocks 2>/dev/null || true
sudo systemctl disable redsocks 2>/dev/null || true

# Create directories
mkdir -p ~/.local/bin
mkdir -p ~/.local/share/applications
mkdir -p ~/.local/share/backgrounds

# Install main app
cp kysettings.py ~/.local/bin/kysettings
chmod +x ~/.local/bin/kysettings

# Install helper scripts
cp scripts/pdanet-proxy ~/.local/bin/pdanet-proxy
chmod +x ~/.local/bin/pdanet-proxy

cp scripts/pdanet ~/.local/bin/pdanet
chmod +x ~/.local/bin/pdanet

cp scripts/game-auto-mute ~/.local/bin/game-auto-mute.py
chmod +x ~/.local/bin/game-auto-mute.py

# Superseded by game-auto-mute; retire any leftover copy so the two daemons
# never fight over the same PipeWire streams.
pkill -f minecraft-auto-mute 2>/dev/null || true
rm -f ~/.local/bin/minecraft-auto-mute.sh

cp scripts/speech-lock ~/.local/bin/speech-lock
chmod +x ~/.local/bin/speech-lock

cp scripts/bt-reset ~/.local/bin/bt-reset
chmod +x ~/.local/bin/bt-reset

# Ensure ~/.local/bin is in PATH
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install GNOME Shell extensions. Copying only puts them on disk — the shell
# scans for new extensions at session start, so they load at the next login,
# which is what the Display page's Restart Session button is for. Each has its
# own toggle in the app and none is enabled here.
mkdir -p ~/.local/share/gnome-shell/extensions
for ext in extensions/*/; do
    uuid="$(basename "$ext")"
    rm -rf "${HOME:?}/.local/share/gnome-shell/extensions/$uuid"
    cp -r "$ext" ~/.local/share/gnome-shell/extensions/
    echo "Installed extension: $uuid"
done

# Install icon
mkdir -p ~/.local/share/icons/hicolor/256x256/apps
cp icons/com.ky.settings.png ~/.local/share/icons/hicolor/256x256/apps/com.ky.settings.png
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true

# Install desktop entry
cp com.ky.settings.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

# Install the portable Kyle's Desktop wallpaper. The app points GNOME at this
# user-owned path when the preset is enabled, so it works on every machine.
cp backgrounds/voidflow-mountains.png \
    ~/.local/share/backgrounds/voidflow-mountains.png

echo ""
echo "Installed successfully!"

# Launch the app (handles dash pinning on first run)
kysettings &
