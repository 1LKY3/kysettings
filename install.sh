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
cp icons/kysettings.png ~/.local/share/icons/hicolor/256x256/apps/kysettings.png
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true

# Install desktop entry
cp kysettings.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

# Pin to dash
python3 -c "
import subprocess, ast
out = subprocess.run(['gsettings', 'get', 'org.gnome.shell', 'favorite-apps'], capture_output=True, text=True)
favs = ast.literal_eval(out.stdout.strip()) if out.returncode == 0 else []
if 'kysettings.desktop' not in favs:
    favs.append('kysettings.desktop')
    subprocess.run(['gsettings', 'set', 'org.gnome.shell', 'favorite-apps', str(favs)])
" 2>/dev/null || true

echo ""
echo "Installed successfully!"

# Launch the app
kysettings &
