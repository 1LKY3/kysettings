#!/usr/bin/env bash
# Package the current KySettings checkout and publish it to kysettings.dustforge.com.
set -euo pipefail
cd "$(dirname "$0")/.."

version=$(/usr/bin/python3 -c "import re; print(re.search(r'__version__ = \"([^\"]+)\"', open('kysettings.py').read()).group(1))")
name="kysettings-$version.tar.gz"
mkdir -p release
rm -f "release/$name"
tar --exclude=.git --exclude=__pycache__ --exclude=release -czf "release/$name" .
sha=$(sha256sum "release/$name" | cut -d' ' -f1)
notes=${NOTES:-"Ky Settings $version"}

/usr/bin/python3 - "$version" "$name" "$sha" "$notes" > release/latest.json <<'PY'
import json
import sys

version, name, sha, notes = sys.argv[1:5]
print(json.dumps({
    'version': version,
    'url': f'https://kysettings.dustforge.com/releases/{name}',
    'sha256': sha,
    'notes': notes,
}, indent=2))
PY

install -m 644 "release/$name" "release/latest.json" /tmp/
scp -q "release/$name" release/latest.json root@192.3.84.103:/var/www/kysettings-releases/
echo "published $version ($sha)"
