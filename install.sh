#!/bin/bash
set -e

echo "=== KySettings Installer ==="

# All dependencies — install everything upfront so nothing needs internet later
ALL_DEPS=(python3 python3-gi gir1.2-adw-1 redsocks xdotool xclip wtype gnome-screenshot)
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

# Install main app
cp kysettings.py ~/.local/bin/kysettings
chmod +x ~/.local/bin/kysettings

# Install helper scripts
cp scripts/pdanet-proxy ~/.local/bin/pdanet-proxy
chmod +x ~/.local/bin/pdanet-proxy

cp scripts/pdanet ~/.local/bin/pdanet
chmod +x ~/.local/bin/pdanet

cp scripts/minecraft-auto-mute ~/.local/bin/minecraft-auto-mute.sh
chmod +x ~/.local/bin/minecraft-auto-mute.sh

cp scripts/speech-lock ~/.local/bin/speech-lock
chmod +x ~/.local/bin/speech-lock

cp scripts/bt-reset ~/.local/bin/bt-reset
chmod +x ~/.local/bin/bt-reset

# Ensure ~/.local/bin is in PATH
if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
    export PATH="$HOME/.local/bin:$PATH"
fi

# Install icon
mkdir -p ~/.local/share/icons/hicolor/256x256/apps
cp icons/com.ky.settings.png ~/.local/share/icons/hicolor/256x256/apps/com.ky.settings.png
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true

# Install desktop entry
cp com.ky.settings.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo ""
echo "Installed successfully!"

# Launch the app (handles dash pinning on first run)
kysettings &
