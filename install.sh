#!/bin/bash
set -e

echo "=== KySettings Installer ==="

# Check for required system packages
MISSING=()
for pkg in python3 python3-gi gir1.2-adw-1; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "Installing missing dependencies: ${MISSING[*]}"
    sudo apt install -y "${MISSING[@]}"
fi

# Create directories
mkdir -p ~/.local/bin
mkdir -p ~/.local/share/applications

# Install main app
cp kysettings.py ~/.local/bin/kysettings
chmod +x ~/.local/bin/kysettings

# Install helper scripts
cp scripts/pdanet-proxy ~/.local/bin/pdanet-proxy
chmod +x ~/.local/bin/pdanet-proxy

cp scripts/minecraft-auto-mute ~/.local/bin/minecraft-auto-mute.sh
chmod +x ~/.local/bin/minecraft-auto-mute.sh

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
