/* Ky Focus
 *
 * Publishes the focused window's PID on the session bus.
 *
 * On Wayland there is deliberately no way for a client to ask which window has
 * focus, and GNOME's own org.gnome.Shell.Introspect refuses callers that are not
 * on its allowlist ("GetWindows is not allowed"). Only code running inside the
 * shell can answer, hence this extension. game-auto-mute is the consumer: without
 * it, a Wayland-native window is invisible in _NET_ACTIVE_WINDOW and a focused
 * Wayland game looks unfocused, so it gets muted while you are playing it.
 *
 * Xwayland windows are covered too — mutter knows their PID as well — so the
 * X11 path in the consumer is a pure fallback for when this is not loaded.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'org.kysettings.Focus';
const OBJECT_PATH = '/org/kysettings/Focus';

const DBUS_XML = `
<node>
  <interface name="org.kysettings.Focus">
    <method name="GetFocusedPid">
      <arg type="i" name="pid" direction="out"/>
    </method>
    <signal name="FocusChanged">
      <arg type="i" name="pid"/>
    </signal>
  </interface>
</node>`;

export default class KyFocusExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(DBUS_XML, this);
        this._dbus.export(Gio.DBus.session, OBJECT_PATH);
        this._nameId = Gio.bus_own_name(
            Gio.BusType.SESSION, BUS_NAME,
            Gio.BusNameOwnerFlags.NONE, null, null, null);

        // Lets the consumer react immediately instead of waiting for its poll.
        this._focusId = global.display.connect('notify::focus-window', () => {
            try {
                this._dbus.emit_signal('FocusChanged',
                    new GLib.Variant('(i)', [this.GetFocusedPid()]));
            } catch (e) {
                console.error(`Ky Focus: ${e}`);
            }
        });
    }

    disable() {
        if (this._focusId) {
            global.display.disconnect(this._focusId);
            this._focusId = 0;
        }
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
    }

    /* 0 means nothing is focused, which is a meaningful answer — the consumer
     * treats it as "no game has focus" rather than as a failure. */
    GetFocusedPid() {
        const win = global.display.focus_window;
        if (!win)
            return 0;

        const pid = win.get_pid();
        return Number.isInteger(pid) && pid > 0 ? pid : 0;
    }
}
