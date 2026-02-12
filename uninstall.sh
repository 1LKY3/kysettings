#!/bin/bash
echo "=== KySettings Uninstaller ==="

# Remove binaries
rm -f ~/.local/bin/kysettings
rm -f ~/.local/bin/pdanet-proxy
pkill -f minecraft-auto-mute 2>/dev/null || true
rm -f ~/.local/bin/minecraft-auto-mute.sh

# Remove icon
rm -f ~/.local/share/icons/hicolor/256x256/apps/kysettings.png
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true

# Remove desktop entry
rm -f ~/.local/share/applications/kysettings.desktop
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

# Remove config/first-run flag
rm -rf ~/.config/kysettings

# Unpin from dash
FAVORITES=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || echo "[]")
if [[ "$FAVORITES" == *"kysettings.desktop"* ]]; then
    NEW=$(echo "$FAVORITES" | sed "s/, 'kysettings.desktop'//" | sed "s/'kysettings.desktop', //" | sed "s/'kysettings.desktop'//")
    gsettings set org.gnome.shell favorite-apps "$NEW" 2>/dev/null || true
fi

echo ""
echo "KySettings has been completely removed."
