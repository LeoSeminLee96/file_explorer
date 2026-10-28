"""DPI-aware pixel metrics, named fonts, and reversible application zoom."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont, ttk


def enable_dpi_awareness():
    """Call before Tk creates a window; older Windows versions use a fallback."""
    if os.name != 'nt':
        return
    import ctypes
    try:
        # System-aware mode is supported by Tk 8.6 without a native window hook.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


class UiScale:
    CHOICES = ('Auto', '90%', '100%', '110%', '125%', '150%')
    PIXELS = ('padx', 'pady', 'highlightthickness', 'borderwidth', 'wraplength',
              'insertwidth', 'spacing1', 'spacing2', 'spacing3', 'sashwidth')

    def __init__(self, root, family):
        self.root, self.family = root, family
        self.dpi_scale = max(1.0, min(3.0, root.winfo_fpixels('1i') / 96.0))
        if os.name == 'nt':
            import ctypes
            try:
                dpi = ctypes.windll.user32.GetDpiForWindow(ctypes.c_void_p(root.winfo_id()))
                if dpi:
                    self.dpi_scale = max(1.0, min(3.0, dpi / 96.0))
            except (AttributeError, OSError):
                pass
        self.factor = 1.0
        self.fonts = {}
        self.widgets, self.packing, self.panes, self.columns, self.tags = [], [], [], [], []
        root.option_add('*Font', self.font(10))
        root.option_add('*TCombobox*Listbox.font', self.font(10))

    def font(self, points, bold=False):
        key = points, bold
        if key not in self.fonts:
            # Negative sizes are pixels: fonts and layout share one scaling rule.
            pixels = max(12, round(points * 4 / 3))
            self.fonts[key] = (tkfont.Font(root=self.root, family=self.family,
                size=-round(pixels * self.factor), weight='bold' if bold else 'normal'), pixels)
        return self.fonts[key][0]

    def capture(self):
        """Record logical metrics once, never rescale already-rounded values."""
        def visit(widget):
            options = widget.keys()
            names = list(self.PIXELS)
            if isinstance(widget, (tk.Frame, tk.PanedWindow)):
                names += ['width', 'height']
            metrics = {name: float(str(widget.cget(name))) for name in names
                       if name in options and str(widget.cget(name)).strip()}
            self.widgets.append((widget, metrics))
            if widget.winfo_manager() == 'pack':
                packing = widget.pack_info()
                self.packing.append((widget, {name: tuple(float(v) for v in self.root.tk.splitlist(str(packing[name])))
                    if not isinstance(packing[name], tuple) else tuple(float(v) for v in packing[name])
                    for name in ('padx', 'pady', 'ipadx', 'ipady')}))
            if isinstance(widget, tk.PanedWindow):
                for pane in widget.panes():
                    metrics = {name: float(str(widget.panecget(pane, name)) or 0) for name in ('minsize', 'width', 'padx', 'pady')}
                    self.panes.append((widget, pane, metrics))
            if isinstance(widget, ttk.Treeview):
                for column in widget['columns']:
                    self.columns.append((widget, column, {name: int(widget.column(column, name)) for name in ('width', 'minwidth')}))
            if isinstance(widget, tk.Text):
                for tag in widget.tag_names():
                    metrics = {name: float(widget.tag_cget(tag, name)) for name in ('spacing1', 'spacing2', 'spacing3') if widget.tag_cget(tag, name)}
                    self.tags.append((widget, tag, metrics))
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)

    def px(self, value):
        return max(1, round(value * self.factor)) if value else 0

    def apply(self, choice):
        if choice not in self.CHOICES:
            choice = 'Auto'
        zoom = 1.0 if choice == 'Auto' else int(choice[:-1]) / 100
        available_w, available_h = self.work_area()
        requested = self.dpi_scale * zoom
        # Very large OS + application zoom can otherwise consume the entire
        # laptop screen with headers and hide the document pane. Fit the minimum
        # usable layout to the work area, retaining the preferred zoom setting.
        self.factor = min(requested, available_w / 980, available_h / 740)
        self.fit_limited = self.factor < requested - .01
        for font, pixels in self.fonts.values():
            font.configure(size=-self.px(pixels))
        for widget, metrics in self.widgets:
            widget.configure(**{name: self.px(value) for name, value in metrics.items()})
        for widget, metrics in self.packing:
            if widget.winfo_manager() == 'pack':
                widget.pack_configure(**{name: tuple(self.px(v) for v in value) for name, value in metrics.items()})
        for widget, pane, metrics in self.panes:
            widget.paneconfigure(pane, **{name: self.px(value) for name, value in metrics.items()})
        for widget, column, metrics in self.columns:
            widget.column(column, **{name: self.px(value) for name, value in metrics.items()})
        for widget, tag, metrics in self.tags:
            widget.tag_configure(tag, **{name: self.px(value) for name, value in metrics.items()})
        style = ttk.Style(self.root)
        style.configure('Treeview', rowheight=max(self.px(39), self.font(10).metrics('linespace') + self.px(14)))
        style.configure('Treeview.Heading', padding=(self.px(12), self.px(10)))
        style.configure('Vertical.TScrollbar', arrowsize=self.px(14))
        style.configure('TCombobox', padding=self.px(3), arrowsize=self.px(14))
        # Let high zoom grow the window when the desktop has room. Never place
        # required controls beyond the work area on a small laptop display.
        self.root.minsize(min(self.px(1120), available_w), min(self.px(740), available_h))
        width = min(max(self.root.winfo_width(), self.px(1400)), available_w)
        height = min(max(self.root.winfo_height(), self.px(900)), available_h)
        if self.root.state() == 'normal':
            self.root.geometry('%dx%d' % (width, height))

    def work_area(self):
        width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                width, height = rect.right - rect.left, rect.bottom - rect.top
        return max(640, width - 24), max(480, height - 48)
