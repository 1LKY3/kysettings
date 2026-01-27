#!/bin/bash
cp kysettings.py ~/.local/bin/kysettings
chmod +x ~/.local/bin/kysettings
cp kysettings.desktop ~/.local/share/applications/
update-desktop-database ~/.local/share/applications/
echo "Installed. Search 'Ky Settings' in launcher."
