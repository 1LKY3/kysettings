#!/bin/bash
echo "=== KySettings Uninstaller ==="

rm -f ~/.local/bin/kysettings
rm -f ~/.local/bin/pdanet-proxy
rm -f ~/.local/share/applications/kysettings.desktop
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true

echo "Removed kysettings, pdanet-proxy, and desktop entry."
