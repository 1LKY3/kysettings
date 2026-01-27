#!/usr/bin/env python3
"""KySettings - Custom GNOME Settings"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio

class KySettings(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.ky.settings')
        self.connect('activate', self.on_activate)
        
    def on_activate(self, app):
        self.win = Adw.ApplicationWindow(application=app)
        self.win.set_title("Ky Settings")
        self.win.set_default_size(500, 400)
        
        # Main layout
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Adw.HeaderBar()
        box.append(header)
        
        # Stack for multiple pages
        self.stack = Adw.ViewStack()
        
        # Add pages
        self.add_display_page()
        # Future: self.add_other_page()
        
        # Switcher in header if multiple pages
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.stack)
        switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)
        
        box.append(self.stack)
        self.win.set_content(box)
        self.win.present()
    
    def add_display_page(self):
        page = Adw.PreferencesPage()
        page.set_icon_name("video-display-symbolic")
        page.set_title("Display")
        
        # Screen Blank group
        group = Adw.PreferencesGroup()
        group.set_title("Screen Blank")
        group.set_description("Extended timeout options")
        
        row = Adw.ComboRow()
        row.set_title("Blank Screen After")
        
        self.blank_options = [
            ("Never", 0),
            ("1 minute", 60),
            ("2 minutes", 120),
            ("3 minutes", 180),
            ("5 minutes", 300),
            ("10 minutes", 600),
            ("15 minutes", 900),
            ("30 minutes", 1800),
            ("1 hour", 3600),
            ("2 hours", 7200),
            ("3 hours", 10800),
            ("4 hours", 14400),
        ]
        
        model = Gtk.StringList()
        for label, _ in self.blank_options:
            model.append(label)
        row.set_model(model)
        
        # Current value
        settings = Gio.Settings.new("org.gnome.desktop.session")
        current = settings.get_uint("idle-delay")
        for i, (_, val) in enumerate(self.blank_options):
            if val == current:
                row.set_selected(i)
                break
        
        row.connect("notify::selected", self.on_blank_changed)
        group.add(row)
        page.add(group)
        
        self.stack.add_titled(page, "display", "Display")
    
    def on_blank_changed(self, row, _):
        _, seconds = self.blank_options[row.get_selected()]
        Gio.Settings.new("org.gnome.desktop.session").set_uint("idle-delay", seconds)

KySettings().run(None)
