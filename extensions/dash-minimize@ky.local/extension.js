/* Dash Minimize
 *
 * Adds a "Minimize" entry to the right-click menu of running apps in the dock
 * (Ubuntu Dock / Dash to Dock), between the window list and Quit.
 *
 * The dock builds that menu from a class it does not export (DockAppIconMenu in
 * appIcons.js), so there is nothing to import. Instead we wrap
 * PopupMenu.PopupMenu.prototype.open just long enough to see the first dock menu
 * open, take its prototype from that live instance, wrap _rebuildMenu there, and
 * unwrap open again. After the first right-click the only patch left in the
 * session is on the dock's own menu class.
 */

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const MENU_CLASS = 'DockAppIconMenu';

/* Windows this app has on the current workspace that are actually on screen.
 * Matches what the dock itself minimizes: showing, minimizable, here and now. */
function minimizableWindows(source) {
    if (!source || typeof source.getInterestingWindows !== 'function')
        return [];

    const workspace = global.workspace_manager.get_active_workspace();
    return source.getInterestingWindows().filter(w =>
        w.get_workspace() === workspace &&
        w.showing_on_its_workspace() &&
        w.can_minimize());
}

export default class DashMinimizeExtension extends Extension {
    enable() {
        this._menuProto = null;
        this._origRebuildMenu = null;
        this._origOpen = null;
        this._watchForDockMenu();
    }

    disable() {
        this._unwatchForDockMenu();

        if (this._menuProto && this._origRebuildMenu) {
            this._menuProto._rebuildMenu = this._origRebuildMenu;
            this._menuProto = null;
            this._origRebuildMenu = null;
        }
    }

    /* Temporary hook on every popup menu, removed as soon as a dock menu
     * identifies itself. */
    _watchForDockMenu() {
        const proto = PopupMenu.PopupMenu.prototype;
        const origOpen = proto.open;
        const extension = this;

        this._origOpen = origOpen;
        proto.open = function (...args) {
            // This wrapper sits in front of every menu in the shell until it
            // catches a dock menu, so it must never be the reason one fails to
            // open.
            try {
                if (this.constructor?.name === MENU_CLASS)
                    extension._adoptMenuClass(this);
            } catch (e) {
                console.error(`Dash Minimize: ${e}`);
                extension._unwatchForDockMenu();
            }
            return origOpen.apply(this, args);
        };
    }

    _unwatchForDockMenu() {
        if (!this._origOpen)
            return;

        PopupMenu.PopupMenu.prototype.open = this._origOpen;
        this._origOpen = null;
    }

    _adoptMenuClass(menu) {
        if (this._menuProto)
            return;

        const proto = Object.getPrototypeOf(menu);
        if (typeof proto._rebuildMenu !== 'function')
            return;

        const origRebuildMenu = proto._rebuildMenu;
        const extension = this;

        this._menuProto = proto;
        this._origRebuildMenu = origRebuildMenu;

        proto._rebuildMenu = function (...args) {
            const result = origRebuildMenu.apply(this, args);
            try {
                extension._addMinimizeItem(this);
            } catch (e) {
                console.error(`Dash Minimize: ${e}`);
            }
            return result;
        };

        // This menu was built before the wrap landed, so fill it in by hand.
        this._unwatchForDockMenu();
        this._addMinimizeItem(menu);
    }

    _addMinimizeItem(menu) {
        const source = menu._source;
        const windows = minimizableWindows(source);
        if (!windows.length)
            return;

        const item = new PopupMenu.PopupMenuItem('Minimize');
        item.connect('activate', () => {
            // Re-read the windows: the menu may have been open a while.
            minimizableWindows(source).forEach(w => w.minimize());
            Main.overview.hide();
        });

        menu.addMenuItem(item, this._insertIndex(menu));
    }

    /* Just above the separator that precedes Quit, so Quit stays last. */
    _insertIndex(menu) {
        const items = menu._getMenuItems();
        const quitIndex = menu._quitMenuItem
            ? items.indexOf(menu._quitMenuItem) : -1;

        if (quitIndex < 0)
            return items.length;

        const separator = items[quitIndex - 1];
        return separator instanceof PopupMenu.PopupSeparatorMenuItem
            ? quitIndex - 1 : quitIndex;
    }
}
