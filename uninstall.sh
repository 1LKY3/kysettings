#!/bin/bash
echo "=== KySettings Uninstaller ==="

# Remove binaries
rm -f ~/.local/bin/kysettings
rm -f ~/.local/bin/pdanet-proxy
pkill -f minecraft-auto-mute 2>/dev/null || true
rm -f ~/.local/bin/minecraft-auto-mute.sh

# Remove icon
rm -f ~/.local/share/icons/hicolor/256x256/apps/com.ky.settings.png
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true

# Remove desktop entry
rm -f ~/.local/share/applications/com.ky.settings.desktop
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

# Remove config/first-run flag
rm -rf ~/.config/kysettings

# Unpin from dash
python3 -c "
import subprocess, ast
out = subprocess.run(['gsettings', 'get', 'org.gnome.shell', 'favorite-apps'], capture_output=True, text=True)
favs = ast.literal_eval(out.stdout.strip()) if out.returncode == 0 else []
if 'com.ky.settings.desktop' in favs:
    favs.remove('com.ky.settings.desktop')
    subprocess.run(['gsettings', 'set', 'org.gnome.shell', 'favorite-apps', str(favs)])
" 2>/dev/null || true

echo ""
echo "KySettings has been completely removed."
