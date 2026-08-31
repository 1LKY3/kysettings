#!/bin/bash
echo "=== KySettings Uninstaller ==="

# Never strand the desktop in Kyle's preset or discard its recovery data.
# Restore before removing the executable; abort and retain everything if even
# one captured setting cannot be recovered safely.
DESKTOP_SNAPSHOT=~/.config/kysettings/desktop-before-kyle.json
if [ -f "$DESKTOP_SNAPSHOT" ]; then
    echo "Restoring the desktop state saved before Kyle's Desktop..."
    if ! ~/.local/bin/kysettings --restore-desktop; then
        echo "ERROR: Desktop restoration was incomplete."
        echo "KySettings and its snapshot have been kept so you can retry."
        exit 1
    fi
fi

# Stop any active PDANet proxy
if [ -f ~/.local/bin/pdanet-proxy ]; then
    sudo ~/.local/bin/pdanet-proxy stop 2>/dev/null || true
fi

# Reset GNOME system proxy if it was set to PDANet
MODE=$(gsettings get org.gnome.system.proxy mode 2>/dev/null)
if [ "$MODE" = "'manual'" ]; then
    HOST=$(gsettings get org.gnome.system.proxy.http host 2>/dev/null)
    if echo "$HOST" | grep -q "192.168.49.1"; then
        echo "Resetting PDANet proxy settings..."
        gsettings set org.gnome.system.proxy mode 'none'
        gsettings reset org.gnome.system.proxy.http host
        gsettings reset org.gnome.system.proxy.http port
        gsettings reset org.gnome.system.proxy.https host
        gsettings reset org.gnome.system.proxy.https port
        gsettings reset org.gnome.system.proxy ignore-hosts
    fi
fi

# Remove proxy env file and apt proxy config
rm -f ~/.proxy_env
sudo rm -f /etc/apt/apt.conf.d/99pdanet-proxy 2>/dev/null || true

# Remove binaries
rm -f ~/.local/bin/kysettings
rm -f ~/.local/bin/pdanet-proxy
rm -f ~/.local/bin/pdanet
pkill -f game-auto-mute 2>/dev/null || true
rm -f ~/.local/bin/game-auto-mute.py
pkill -f minecraft-auto-mute 2>/dev/null || true
rm -f ~/.local/bin/minecraft-auto-mute.sh
pkill -f speech-lock 2>/dev/null || true
rm -f ~/.local/bin/speech-lock
rm -f ~/.local/bin/bt-reset

# Remove GNOME Shell extensions
for uuid in dash-minimize@ky.local ky-focus@ky.local; do
    gnome-extensions disable "$uuid" 2>/dev/null || true
    rm -rf "${HOME:?}/.local/share/gnome-shell/extensions/$uuid"
done

# Remove icon
rm -f ~/.local/share/icons/hicolor/256x256/apps/com.ky.settings.png
gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null || true

# Remove desktop entry
rm -f ~/.local/share/applications/com.ky.settings.desktop
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

# Remove the wallpaper bundled exclusively for Kyle's Desktop.
rm -f ~/.local/share/backgrounds/voidflow-mountains.png

# Remove generated state but preserve user-maintained configuration such as
# game-mute-markers.txt. A successfully restored desktop snapshot is already
# removed by KySettings itself.
rm -f ~/.config/kysettings/.installed
rm -f ~/.config/kysettings/.ss_cleanup
rm -f ~/.config/kysettings/window.json
rm -f ~/.config/kysettings/game-auto-mute.lock
rm -f ~/.config/kysettings/wayland-focus.enabled
rmdir ~/.config/kysettings 2>/dev/null || true

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
echo "KySettings has been removed."
echo ""
echo "The following packages were installed as dependencies and are still present:"
echo "  python3-gi  gir1.2-adw-1  redsocks"
echo ""
echo "To remove them manually if no longer needed:"
echo "  sudo apt remove python3-gi gir1.2-adw-1 redsocks"
