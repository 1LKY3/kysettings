"""Kyle's Desktop: explicit preset, reversible feature adapters, no resident worker."""
import base64
import fcntl
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import time
from gi.repository import Gio, GLib

HOME = Path.home()
CONFIG = HOME / '.config/kysettings'
SNAPSHOT = CONFIG / 'desktop-before-kyle.json'
STATE = CONFIG / 'desktop-preset.json'
VERSION = 2
KB = 'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding'
KEYS = 'org.gnome.settings-daemon.plugins.media-keys'
SHELL = 'org.gnome.shell'
WORKSPACE = 'workspace-monitor-mvp@ky.local'
MINIMIZE = 'dash-minimize@ky.local'
FOCUS = 'ky-focus@ky.local'
SCREENSHOTS = ['<Ctrl><Shift>s', '<Shift><Super>s']
DATE_COMMAND = 'bash -c \'wl-copy "$(date +"%F %T")"\''
BASE = [
 ('org.gnome.desktop.interface', 'gtk-theme', 'Yaru-sage-dark'),
 ('org.gnome.desktop.interface', 'color-scheme', 'prefer-dark'),
 ('org.gnome.desktop.interface', 'icon-theme', 'Yaru-sage'),
 ('org.gnome.desktop.interface', 'cursor-theme', 'Yaru'),
 ('org.gnome.desktop.interface', 'font-name', 'Ubuntu Sans 11'),
 ('org.gnome.desktop.interface', 'document-font-name', 'Sans 11'),
 ('org.gnome.desktop.interface', 'monospace-font-name', 'Ubuntu Sans Mono 13'),
 ('org.gnome.desktop.wm.preferences', 'button-layout', ':minimize,maximize,close'),
 ('org.gnome.shell.extensions.dash-to-dock', 'dock-position', 'BOTTOM'),
 ('org.gnome.shell.extensions.dash-to-dock', 'dash-max-icon-size', 40),
 ('org.gnome.shell.extensions.dash-to-dock', 'autohide', True),
 ('org.gnome.mutter', 'center-new-windows', False),
 ('org.gnome.desktop.background', 'picture-options', 'zoom'),
 ('org.gnome.desktop.session', 'idle-delay', 0),
 ('org.gnome.desktop.screensaver', 'idle-activation-enabled', False),
 ('org.gnome.settings-daemon.plugins.power', 'idle-dim', False),
 ('org.gnome.shell.extensions.workspace-monitor', 'cycle-monitors', True),
 ('org.gnome.shell.extensions.workspace-monitor', 'all-displays', False),
]


def run(*argv, timeout=15, input=None):
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, input=input)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or f'{argv[0]} failed')
    return p.stdout.strip()


def helper(name):
    source = Path(__file__).resolve().parent / 'scripts' / name
    return str(source if source.exists() else HOME / '.local/bin' / name)


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        os.chmod(tmp, 0o600)
        json.dump(data, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def read_file(path):
    if path.is_symlink():
        return {'symlink': os.readlink(path)}
    if not path.exists():
        return None
    return {'data': base64.b64encode(path.read_bytes()).decode(),
            'mode': path.stat().st_mode & 0o777}


def write_file(path, value):
    if value is None:
        path.unlink(missing_ok=True)
    elif 'symlink' in value:
        path.unlink(missing_ok=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(value['symlink'])
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            path.unlink()
        path.write_bytes(base64.b64decode(value['data']))
        path.chmod(value['mode'])


def settings(schema, path=None):
    source = Gio.SettingsSchemaSource.get_default()
    found = source.lookup(schema, True) if source else None
    if found is None:
        for root in (HOME / '.local/share/gnome-shell/extensions', Path('/usr/share/gnome-shell/extensions')):
            for directory in root.glob('*/schemas'):
                if (directory / 'gschemas.compiled').exists():
                    local = Gio.SettingsSchemaSource.new_from_directory(str(directory), source, False)
                    found = local.lookup(schema, False)
                    if found:
                        break
            if found:
                break
    if found is None:
        raise RuntimeError(f'Missing settings: {schema}')
    return Gio.Settings.new_full(found, None, path)


def get(schema, key, path=None):
    s = settings(schema, path)
    if not s.props.settings_schema.has_key(key):
        raise RuntimeError(f'Missing setting: {schema} {key}')
    return s.get_value(key).unpack()


def put(schema, key, value, path=None):
    s = settings(schema, path)
    variant = GLib.Variant(s.get_value(key).get_type_string(), value)
    if not s.set_value(key, variant):
        raise RuntimeError(f'Setting is locked: {schema} {key}')
    Gio.Settings.sync()


def capture_key(schema, key, path=None):
    s = settings(schema, path)
    if not s.props.settings_schema.has_key(key):
        raise RuntimeError(f'Missing setting: {schema} {key}')
    v = s.get_user_value(key)
    return v.print_(True) if v is not None else None


def restore_key(schema, key, value, path=None):
    s = settings(schema, path)
    if not s.is_writable(key):
        raise RuntimeError(f'Setting is locked: {schema} {key}')
    if value is None:
        s.reset(key)
    elif not s.set_value(key, GLib.Variant.parse(None, value, None, None)):
        raise RuntimeError(f'Could not restore {schema} {key}')
    Gio.Settings.sync()


class Feature:
    def __init__(self, name, capture, apply, restore, matches):
        self.name, self.capture, self.apply, self.restore, self.matches = name, capture, apply, restore, matches


def setting_feature(schema, key, value):
    return Feature(f'{schema}/{key}', lambda: capture_key(schema, key),
                   lambda: put(schema, key, value),
                   lambda old: restore_key(schema, key, old),
                   lambda: get(schema, key) == value)


def extension_enabled(uuid):
    return uuid in get(SHELL, 'enabled-extensions') and uuid not in get(SHELL, 'disabled-extensions')


def extension_set(uuid, enabled):
    for key, want in [('enabled-extensions', enabled), ('disabled-extensions', not enabled)]:
        values = get(SHELL, key)
        if want and uuid not in values:
            values.append(uuid)
        if not want:
            values = [x for x in values if x != uuid]
        put(SHELL, key, values)


def extension_feature(uuid, enabled):
    def capture():
        return {k: uuid in get(SHELL, k) for k in ['enabled-extensions', 'disabled-extensions']}
    def restore(old):
        for key, present in old.items():
            values = [x for x in get(SHELL, key) if x != uuid]
            if present:
                values.append(uuid)
            put(SHELL, key, values)
    def apply():
        if enabled and not any((root / uuid).exists() for root in
                [HOME / '.local/share/gnome-shell/extensions', Path('/usr/share/gnome-shell/extensions')]):
            raise RuntimeError(f'Install extension {uuid}; then Reapply')
        extension_set(uuid, enabled)
    return Feature('extension:' + uuid, capture, apply, restore,
                   lambda: extension_enabled(uuid) == enabled)


def flag_feature(name, path, enabled):
    def apply():
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        else:
            path.unlink(missing_ok=True)
    return Feature(name, lambda: read_file(path), apply,
                   lambda old: write_file(path, old), lambda: path.exists() == enabled)


def mute_running():
    path = CONFIG / 'game-auto-mute.lock'
    if not path.exists():
        return False
    with path.open('r') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def mute_set(running):
    if running == mute_running():
        return
    if running:
        script = HOME / '.local/bin/game-auto-mute.py'
        if not script.exists():
            raise RuntimeError('Install the Game Auto-Mute helper')
        subprocess.Popen([str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        pid = int((CONFIG / 'game-auto-mute.lock').read_text().strip())
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes()
        if b'game-auto-mute' not in cmd:
            raise RuntimeError('Game Auto-Mute PID does not match its helper')
        os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if mute_running() == running:
            return
        time.sleep(.05)
    raise RuntimeError('Game Auto-Mute did not change state')


def game_mute_feature():
    path = HOME / '.config/autostart/game-auto-mute.desktop'
    def capture():
        return {'file': read_file(path), 'running': mute_running()}
    def apply():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[Desktop Entry]\nType=Application\nName=Game Auto-Mute\n'
                        f'Exec={HOME}/.local/bin/game-auto-mute.py\n'
                        'X-GNOME-Autostart-enabled=true\nNoDisplay=true\n')
        mute_set(True)
    def restore(old):
        write_file(path, old['file'])
        mute_set(old['running'])
    def matches():
        return path.exists() and 'X-GNOME-Autostart-enabled=false' not in path.read_text() and mute_running()
    return Feature('Game Auto-Mute', capture, apply, restore, matches)


def date_feature():
    def paths():
        return get(KEYS, 'custom-keybindings')
    def date_paths():
        return [p for p in paths() if get(KB, 'name', p) == 'ky-insert-date']
    def capture():
        used = paths()
        i = 0
        while (candidate := f'/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom{i}/') in used:
            i += 1
        selected = date_paths() or [candidate]
        return {'paths': capture_key(KEYS, 'custom-keybindings'),
                'entries': {p: {k: capture_key(KB, k, p) for k in ['name', 'command', 'binding']}
                            for p in selected}}
    def apply():
        selected = date_paths()
        if not selected:
            selected = list(capture()['entries'])
        for p in selected:
            for key, value in [('name', 'ky-insert-date'), ('command', DATE_COMMAND), ('binding', '<Control><Alt>period')]:
                put(KB, key, value, p)
        put(KEYS, 'custom-keybindings', list(dict.fromkeys(paths() + selected)))
    def restore(old):
        for p, keys in old['entries'].items():
            for k, value in keys.items():
                restore_key(KB, k, value, p)
        restore_key(KEYS, 'custom-keybindings', old['paths'])
    def matches():
        return any(get(KB, 'command', p) == DATE_COMMAND and
                   get(KB, 'binding', p) in ['<Control><Alt>period', '<Ctrl><Alt>period'] for p in date_paths())
    return Feature('Type Date', capture, apply, restore, matches)


def terminal_feature():
    def current():
        return run('/usr/bin/python3', helper('ky-terminal'), 'status') == 'enabled'
    def set_to(wanted):
        if current() != wanted:
            if wanted and not Path('/usr/bin/lxterminal').exists():
                run('pkexec', '/usr/bin/apt-get', 'install', '-y', 'lxterminal', timeout=300)
            run('/usr/bin/python3', helper('ky-terminal'), 'enable' if wanted else 'disable', timeout=300)
    def restore(wanted):
        # A failed enable can leave a recoverable snapshot even when the
        # aggregate status is still off. Do not mistake that for restoration.
        if not wanted and (CONFIG / 'terminal-before.json').exists():
            run('/usr/bin/python3', helper('ky-terminal'), 'disable', timeout=300)
        else:
            set_to(wanted)
    return Feature('LXTerminal', current, lambda: set_to(True), restore, current)


def keychron_feature():
    def current():
        return run('/usr/bin/python3', helper('keychron-super'), 'status') == 'enabled'
    def set_to(wanted):
        if current() != wanted:
            run('pkexec', '/usr/bin/python3', helper('keychron-super'),
                'enable' if wanted else 'disable', timeout=120)
    return Feature('Keychron Super Key', current, lambda: set_to(True), set_to, current)


def bluetooth_feature():
    def current():
        info = run('bluetoothctl', 'show')
        if 'Controller ' not in info:
            return None
        return 'Powered: yes' in info
    def set_to(value):
        if value is not None and current() != value:
            run('bluetoothctl', 'power', 'on' if value else 'off')
            if current() != value:
                raise RuntimeError('Bluetooth power did not change')
    def capture():
        try:
            return current()
        except RuntimeError as e:
            if 'No default controller' in str(e):
                return None
            raise
    return Feature('Bluetooth', capture, lambda: set_to(True) if capture() is not None else None,
                   set_to, lambda: capture() in (True, None))


def apt_write(value):
    path = '/etc/apt/apt.conf.d/99pdanet-proxy'
    # Fixed destination; JSON data is stdin, never executable code.
    code = ('import json,sys,base64,pathlib; p=pathlib.Path(' + repr(path) + '); '
            'v=json.load(sys.stdin); '
            'p.unlink(missing_ok=True) if v is None else '
            '(p.write_bytes(base64.b64decode(v["data"])),p.chmod(v["mode"]))')
    run('pkexec', '/usr/bin/python3', '-c', code, input=json.dumps(value), timeout=120)


def proxy_feature():
    keys = [('org.gnome.system.proxy', 'mode'), ('org.gnome.system.proxy', 'ignore-hosts')]
    keys += [(f'org.gnome.system.proxy.{s}', k) for s in ['http', 'https'] for k in ['host', 'port']]
    env = HOME / '.proxy_env'
    apt = Path('/etc/apt/apt.conf.d/99pdanet-proxy')
    def active():
        return get('org.gnome.system.proxy', 'mode') == 'manual' and get('org.gnome.system.proxy.http', 'host') == '192.168.49.1'
    def capture():
        return {'keys': [capture_key(s, k) for s, k in keys], 'env': read_file(env), 'apt': read_file(apt)}
    def apply():
        if active():
            put('org.gnome.system.proxy', 'mode', 'none')
        if env.exists() and '192.168.49.1' in env.read_text():
            env.unlink()
        if apt.exists() and '192.168.49.1' in apt.read_text():
            apt_write(None)
    def restore(old):
        for (s, k), v in zip(keys, old['keys']):
            restore_key(s, k, v)
        write_file(env, old['env'])
        if read_file(apt) != old['apt']:
            apt_write(old['apt'])
    def matches():
        return not active() and not any(p.exists() and '192.168.49.1' in p.read_text() for p in [env, apt])
    return Feature('PDANet Proxy Off', capture, apply, restore, matches)


def transparent_feature():
    def current():
        p = subprocess.run([helper('pdanet-proxy'), 'status'], capture_output=True, text=True, timeout=10)
        return 'running' in p.stdout
    def set_to(wanted):
        if current() != wanted:
            run('pkexec', helper('pdanet-proxy'), 'start' if wanted else 'stop', timeout=120)
            if current() != wanted:
                raise RuntimeError('Transparent Proxy did not change state')
    return Feature('Transparent Proxy Off', current, lambda: set_to(False), set_to, lambda: not current())


def dpms_feature():
    def current():
        if os.environ.get('XDG_SESSION_TYPE') != 'x11':
            return None
        output = run('xset', 'q')
        times = re.search(r'Standby:\s*(\d+)\s+Suspend:\s*(\d+)\s+Off:\s*(\d+)', output)
        if not times:
            return None
        return {'timeouts': list(map(int, times.groups())), 'enabled': 'DPMS is Enabled' in output}
    def restore(value):
        if value is not None:
            run('xset', 'dpms', *map(str, value['timeouts']))
            run('xset', '+dpms' if value['enabled'] else '-dpms')
    def apply():
        if current() is not None:
            restore({'timeouts': [0, 0, 0], 'enabled': False})
    return Feature('Monitor power timeout (X11)', current, apply, restore,
                   lambda: current() in (None, {'timeouts': [0, 0, 0], 'enabled': False}))


def features():
    result = [setting_feature(*row) for row in BASE]
    wallpaper = HOME / '.local/share/backgrounds/voidflow-mountains.png'
    for key in ['picture-uri', 'picture-uri-dark']:
        f = setting_feature('org.gnome.desktop.background', key, wallpaper.as_uri())
        original = f.apply
        def apply_wallpaper(original=original):
            if not wallpaper.exists():
                raise RuntimeError('Install the bundled Kyle desktop wallpaper')
            original()
        f.apply = apply_wallpaper
        match = f.matches
        f.matches = lambda match=match: wallpaper.exists() and match()
        result.append(f)
    for uuid, enabled in [(WORKSPACE, True), (MINIMIZE, True), (FOCUS, False),
                          ('hidetopbar@mathieu.bidon.ca', False), ('blur-my-shell@aunetx', False)]:
        result.append(extension_feature(uuid, enabled))
    # Absent effects extension is already off; do not require installing it.
    for section in ['applications', 'panel', 'overview']:
        schema = f'org.gnome.shell.extensions.blur-my-shell.{section}'
        try:
            settings(schema)
        except RuntimeError:
            continue
        result.append(setting_feature(schema, 'blur', False))
    result.append(flag_feature('Wayland Focus Off', CONFIG / 'wayland-focus.enabled', False))
    result.append(flag_feature('Auto-delete Screenshots', CONFIG / '.ss_cleanup', True))
    result += [game_mute_feature(), date_feature(), terminal_feature(), keychron_feature(),
               bluetooth_feature(), proxy_feature(), transparent_feature(), dpms_feature()]
    def pin():
        values = get(SHELL, 'favorite-apps')
        if 'com.ky.settings.desktop' not in values:
            put(SHELL, 'favorite-apps', values + ['com.ky.settings.desktop'])
    result.append(Feature('Pin KySettings to Dash', lambda: capture_key(SHELL, 'favorite-apps'), pin,
                          lambda v: restore_key(SHELL, 'favorite-apps', v),
                          lambda: 'com.ky.settings.desktop' in get(SHELL, 'favorite-apps')))
    schema, key = 'org.gnome.shell.keybindings', 'show-screenshot-ui'
    result.append(Feature('Screenshot shortcuts', lambda: capture_key(schema, key),
        lambda: put(schema, key, list(dict.fromkeys(get(schema, key) + SCREENSHOTS))),
        lambda v: restore_key(schema, key, v), lambda: all(b in get(schema, key) for b in SCREENSHOTS)))
    return result


class Preset:
    def __init__(self, items=None, snapshot=SNAPSHOT, state=STATE):
        self.check_runtime = items is None
        self.items = items if items is not None else features()
        self.snapshot, self.state = snapshot, state

    def load_snapshot(self):
        data = json.loads(self.snapshot.read_text())
        if data.get('version') == 1:
            entries = {}
            for item in data['settings']:
                value = GLib.Variant(item['type'], item['value']).print_(True) if item.get('user_set') else None
                entries[item['schema'] + '/' + item['key']] = value
            entries['extension:' + MINIMIZE] = {'enabled-extensions': data.get('dash_minimize_enabled', False),
                                                'disabled-extensions': False}
            return {'version': VERSION, 'entries': entries, 'migrated': True}
        if data.get('version') != VERSION or not isinstance(data.get('entries'), dict):
            raise RuntimeError('Unsupported or invalid desktop snapshot; nothing changed')
        return data

    def status(self):
        marker = json.loads(self.state.read_text()) if self.state.exists() else None
        if marker is None and self.snapshot.exists():
            marker = {'phase': 'legacy', 'errors': ['A saved baseline exists. Reapply to update the preset, or turn it off to restore.']}
        differences, unavailable = [], []
        for item in self.items:
            try:
                if not item.matches():
                    differences.append(item.name)
            except Exception as exc:
                unavailable.append(f'{item.name}: {exc}')
        pending = []
        for uuid in ([WORKSPACE, MINIMIZE] if self.check_runtime else []):
            try:
                output = run('gnome-extensions', 'info', uuid)
                if 'State: ACTIVE' not in output:
                    pending.append(uuid + ': extension is not active; a new login may be required')
            except Exception:
                pending.append(uuid + ': extension is unavailable')
        if self.check_runtime:
            for path, label in [(Path('/usr/bin/lxterminal'), 'LXTerminal'),
                                (HOME / '.local/bin/game-auto-mute.py', 'Game Auto-Mute helper'),
                                (HOME / '.local/share/backgrounds/voidflow-mountains.png', 'Kyle desktop wallpaper')]:
                if not path.exists():
                    pending.append(label + ': not installed')
        if not marker:
            label = 'Not applied'
        elif marker.get('phase') != 'applied' or unavailable or pending:
            label = 'Incomplete'
        elif differences:
            label = 'Customized'
        else:
            label = 'Applied'
        return {'status': label, 'managed': marker is not None, 'differences': differences,
                'unavailable': unavailable, 'pending': pending,
                'errors': marker.get('errors', []) if marker else [],
                'snapshot': self.snapshot.exists()}

    def apply(self):
        data = self.load_snapshot() if self.snapshot.exists() else {'version': VERSION, 'entries': {}}
        errors, available = [], []
        # Capture every feature before the first mutation. Reapply only adds
        # newly introduced features; never overwrite the original baseline.
        for item in self.items:
            try:
                if item.name not in data['entries']:
                    data['entries'][item.name] = item.capture()
                available.append(item)
            except Exception as exc:
                errors.append(f'{item.name}: {exc}')
        atomic(self.snapshot, data)
        atomic(self.state, {'version': VERSION, 'phase': 'applying', 'errors': errors})
        for item in available:
            try:
                if not item.matches():
                    item.apply()
                if not item.matches():
                    raise RuntimeError('The requested value did not take effect')
            except Exception as exc:
                errors.append(f'{item.name}: {exc}')
        atomic(self.state, {'version': VERSION, 'phase': 'incomplete' if errors else 'applied', 'errors': errors})
        return errors

    def restore(self):
        if not self.snapshot.exists():
            raise RuntimeError('No previous desktop snapshot exists; nothing was reset')
        data = self.load_snapshot()
        by_name = {item.name: item for item in self.items}
        errors = []
        atomic(self.state, {'version': VERSION, 'phase': 'restoring', 'errors': []})
        for name, old in reversed(list(data['entries'].items())):
            try:
                item = by_name.get(name)
                if item is None:
                    # Preserve restorability if an extension was removed after capture.
                    if '/' in name and name.startswith('org.'):
                        schema, key = name.rsplit('/', 1)
                        restore_key(schema, key, old)
                    else:
                        raise RuntimeError('Feature is unavailable; restore it before retrying')
                else:
                    item.restore(old)
            except Exception as exc:
                errors.append(f'{name}: {exc}')
        if errors:
            atomic(self.state, {'version': VERSION, 'phase': 'restore-failed', 'errors': errors})
        else:
            self.snapshot.unlink()
            self.state.unlink(missing_ok=True)
        return errors


def describe(text):
    """Readable labels; snapshot IDs remain stable."""
    labels = {'LXTerminal': 'LXTerminal', 'extension:' + WORKSPACE: 'Workspace Monitor',
              'extension:' + MINIMIZE: 'Minimize on Right-Click',
              'extension:' + FOCUS: 'Wayland Focus',
              'extension:hidetopbar@mathieu.bidon.ca': 'Hide Top Bar',
              'extension:blur-my-shell@aunetx': 'Blur effects'}
    for schema, key, _ in BASE:
        labels[schema + '/' + key] = key.replace('-', ' ').capitalize()
    for section, label in [('applications', 'Window effects'), ('panel', 'Blur Top Bar'), ('overview', 'Blur Overview')]:
        labels[f'org.gnome.shell.extensions.blur-my-shell.{section}/blur'] = label
    for old, new in labels.items():
        text = text.replace(old, new)
    return text


def main(argv):
    if argv not in (['status'], ['apply'], ['restore']):
        raise RuntimeError('Usage: ky-desktop status|apply|restore')
    if argv == ['status']:
        print(json.dumps(Preset().status()))
        return 0
    CONFIG.mkdir(parents=True, exist_ok=True)
    with (CONFIG / 'desktop-preset.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preset = Preset()
        errors = preset.apply() if argv == ['apply'] else preset.restore()
        print(json.dumps({'errors': errors, 'status': preset.status()}))
        return 1 if errors else 0


if __name__ == '__main__':
    import sys
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
