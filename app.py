from __future__ import annotations

import argparse
import json
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import tempfile
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from explorer.files import PAGE_SIZE, page, scan
from explorer.memory import profile
from explorer.service import Worker
from explorer.ai import load_config
from explorer.summary import extractive_sentence
from explorer.ui import UiScale, enable_dpi_awareness

BASE = Path(__file__).resolve().parent
BG, WHITE, INK, MUTED, BORDER, TEAL = '#f7f8fa', '#ffffff', '#202b38', '#7a8494', '#e7eaf0', '#087f73'
FONT = 'Segoe UI' if os.name == 'nt' else 'DejaVu Sans'


def size_label(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return ('%d %s' if unit == 'B' else '%.1f %s') % (size, unit)
        size /= 1024


def date_label(value):
    return datetime.fromtimestamp(value).strftime('%Y.%m.%d  %H:%M')


class Explorer(tk.Tk):
    def __init__(self, folder=None, state_dir=None, ai_enabled=True):
        enable_dpi_awareness()
        super().__init__()
        self.title('Document Explorer')
        self.geometry('1400x900')
        self.minsize(1120, 740)
        self.configure(bg=BG)
        self.state_dir = Path(state_dir or BASE / '.data')
        self.state_dir.mkdir(parents=True, exist_ok=True)
        settings = self.load_settings()
        self.ui = UiScale(self, FONT)
        self.scale_var = tk.StringVar(value=settings.get('ui_scale', 'Auto'))
        if self.scale_var.get() not in UiScale.CHOICES:
            self.scale_var.set('Auto')
        self.summary_workspace = None
        self.summary_state = None
        # Migrate earlier builds: summary/extraction results are no longer stored.
        for suffix in ('', '-wal', '-shm'):
            try:
                (self.state_dir / ('documents.db' + suffix)).unlink(missing_ok=True)
            except OSError:
                pass
        self.profile = profile()
        self.ai_config = load_config() if ai_enabled else None
        self.fallback_result = None
        self.worker = Worker()
        self.scan_cancel = threading.Event()
        self.scan_thread = None
        self.scan_events = queue.Queue(maxsize=2)
        self.scan_requests = queue.Queue(maxsize=1)
        self.scan_shutdown = threading.Event()
        threading.Thread(target=self.scan_loop, daemon=True).start()
        self.view_id = 0
        self.snapshot = None
        self.ready = False
        self.scan_running = False
        self.selected = None
        self.selected_stamp = None
        self.kind = None
        self.info = {}
        self.summary_result = None
        self.summary_offset = 0
        self.history = []
        self.history_position = -1
        self.offset, self.total = 0, 0
        self.sort, self.descending = 'name', False
        self.document_filter = False
        self.search_results = False
        self.searching = False
        self.matches = {}
        self.mode = 'preview'
        self.preview_text = ''
        self.debounce = None
        self._style()
        self._build()
        self.ui.capture()
        self.ui.apply(self.scale_var.get())
        self.bind('<Configure>', self._window_resized, add='+')
        self.after_idle(self._adapt_layout)
        self._shortcuts()
        self.protocol('WM_DELETE_WINDOW', self.close)
        initial = folder or settings.get('folder') or str(BASE / 'sample_documents')
        if not Path(initial).is_dir():
            initial = str(BASE)
        self.navigate(initial)
        self.after(60, self.poll)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Treeview', background=WHITE, fieldbackground=WHITE, foreground=INK,
                        font=self.ui.font(10), rowheight=39, borderwidth=0)
        style.configure('Treeview.Heading', background='#f8f9fb', foreground=MUTED,
                        relief='flat', borderwidth=0, padding=(12, 10), font=self.ui.font(9))
        style.map('Treeview', background=[('selected', '#e6f3ef')], foreground=[('selected', '#075d55')])
        style.map('Treeview.Heading', background=[('active', '#eef1f5')])
        style.configure('Vertical.TScrollbar', arrowsize=12, background='#dde2e8', troughcolor=WHITE, borderwidth=0)

    def label(self, parent, text='', color=INK, size=10, bold=False, bg=None, **kwargs):
        return tk.Label(parent, text=text, fg=color, bg=bg or parent.cget('bg'), font=self.ui.font(size, bold), **kwargs)

    def button(self, parent, text, command, primary=False, **kwargs):
        return tk.Button(parent, text=text, command=command, bg=TEAL if primary else WHITE,
                         fg=WHITE if primary else INK, activebackground='#09695f' if primary else '#eef2f5',
                         activeforeground=WHITE if primary else INK, relief='flat', bd=0, cursor='hand2',
                         padx=14, pady=8, disabledforeground='#b4bbc4', **kwargs)

    def _build(self):
        sidebar = tk.Frame(self, bg='#eef1f5', width=248)
        self.sidebar = sidebar
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg='#eef1f5')
        brand.pack(fill='x', padx=18, pady=(22, 20))
        self.label(brand, '▤', TEAL, 27, True).pack(side='left', padx=(0, 10))
        names = tk.Frame(brand, bg='#eef1f5')
        names.pack(side='left')
        self.brand_title = self.label(names, 'Documents', size=16, bold=True)
        self.brand_title.pack(anchor='w')
        self.label(names, 'DOCUMENT EXPLORER', MUTED, 7).pack(anchor='w', pady=(3, 0))
        self.button(sidebar, '+  Open folder', self.choose_folder, True).pack(fill='x', padx=19, pady=(0, 20))
        self.label(sidebar, 'LIBRARY', MUTED, 8, bold=True).pack(anchor='w', padx=24, pady=(0, 12))
        locations = [('▦   Sample documents', BASE / 'sample_documents'), ('⌂   Documents', Path.home() / 'Documents'),
                     ('▣   Desktop', Path.home() / 'Desktop'), ('↓   Downloads', Path.home() / 'Downloads'),
                     ('‹/›   Project', BASE), ('⌂   Home', Path.home())]
        for name, path in locations:
            button = self.button(sidebar, name, lambda p=path: self.navigate(p), anchor='w')
            button.configure(bg='#eef1f5', pady=8)
            button.pack(fill='x', padx=12, pady=2)
        self.label(sidebar, 'HOW IT WORKS', MUTED, 8, bold=True).pack(anchor='w', padx=24, pady=(16, 12))
        for text in ('✓  Files stay on this PC', '✓  Search without a model', '✓  Summaries on request'):
            self.label(sidebar, text, '#647384', 9).pack(anchor='w', padx=23, pady=7)
        bottom = tk.Frame(sidebar, bg='#e4e9ef')
        bottom.pack(side='bottom', fill='x', padx=16, pady=20)
        self.label(bottom, '●  Low memory use', TEAL, 9, True).pack(anchor='w', padx=12, pady=(13, 5))
        self.label(bottom, '%s · 1 parser' % self.profile.name, '#687583', 8).pack(anchor='w', padx=12, pady=(0, 12))

        workspace = tk.Frame(self, bg=BG)
        self.workspace = workspace
        workspace.pack(side='left', fill='both', expand=True)
        header = tk.Frame(workspace, bg=WHITE, height=96)
        header.pack(fill='x')
        header.pack_propagate(False)
        header_actions = tk.Frame(header, bg=WHITE)
        header_actions.pack(side='right', padx=24, pady=12)
        scale_row = tk.Frame(header_actions, bg=WHITE)
        scale_row.pack(anchor='e')
        self.scale_label = self.label(scale_row, 'UI scale', MUTED, 9)
        self.scale_label.pack(side='left', padx=(0, 8))
        self.scale_selector = ttk.Combobox(scale_row, textvariable=self.scale_var, state='readonly',
                                           values=UiScale.CHOICES, width=7, font=self.ui.font(10))
        self.scale_selector.pack(side='left')
        self.scale_selector.bind('<<ComboboxSelected>>', lambda event: self.change_scale())
        self.label(header_actions, '●  LOCAL WORKSPACE', TEAL, 8, True).pack(anchor='e', pady=(7, 0))
        heading = tk.Frame(header, bg=WHITE)
        heading.pack(side='left', padx=28, pady=18)
        self.label(heading, 'Explore your documents', size=18, bold=True).pack(anchor='w')
        self.label(heading, 'Find files, preview content, and read the essentials.', MUTED, 9, wraplength=400, justify='left').pack(anchor='w', pady=(5, 0))
        tk.Frame(workspace, height=1, bg=BORDER).pack(fill='x')
        toolbar = tk.Frame(workspace, bg=BG)
        toolbar.pack(fill='x', padx=24, pady=(20, 12))
        self.button(toolbar, '←', self.back).pack(side='left', padx=(0, 5))
        self.button(toolbar, '↑', self.up).pack(side='left', padx=(0, 8))
        self.button(toolbar, 'Open', self.choose_folder).pack(side='left', padx=(0, 8))
        self.path_var = tk.StringVar()
        self.path_entry = tk.Entry(toolbar, textvariable=self.path_var, bg=WHITE, fg='#536171', relief='flat',
                                   highlightthickness=1, highlightbackground=BORDER, highlightcolor=TEAL)
        self.path_entry.pack(side='left', fill='x', expand=True, ipady=10)
        self.path_entry.bind('<Return>', lambda event: self.navigate(self.path_var.get()))
        self.button(toolbar, '↻', self.refresh).pack(side='left', padx=(8, 0))
        searchbar = tk.Frame(workspace, bg=BG)
        searchbar.pack(fill='x', padx=24, pady=(0, 17))
        search_box = tk.Frame(searchbar, bg=WHITE, highlightthickness=1, highlightbackground=BORDER)
        search_box.pack(side='left', fill='x', expand=True)
        self.label(search_box, '⌕', TEAL, 19).pack(side='left', padx=(13, 8))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(search_box, textvariable=self.search_var, relief='flat', fg=INK, bg=WHITE,
                                     insertbackground=TEAL)
        self.search_entry.pack(side='left', fill='x', expand=True, ipady=11)
        self.search_entry.bind('<Return>', lambda event: self.search())
        self.search_entry.bind('<KeyRelease>', self.search_changed)
        self.label(search_box, 'Ctrl + F', '#a3abb6', 8).pack(side='right', padx=12)
        self.search_mode = tk.StringVar(value='Name / path')
        selector = ttk.Combobox(searchbar, textvariable=self.search_mode, state='readonly',
                                values=('Name / path', 'File contents'), width=15)
        selector.pack(side='left', padx=(10, 8), ipady=9)
        self.recursive = tk.BooleanVar(value=False)
        tk.Checkbutton(searchbar, text='Subfolders', variable=self.recursive, bg=BG, fg='#687583',
                       activebackground=BG, selectcolor=WHITE).pack(side='left', padx=5)
        self.button(searchbar, 'Search', self.search, True).pack(side='left', padx=(5, 0))

        content = tk.PanedWindow(workspace, orient='horizontal', bg=BG, sashwidth=14, bd=0, sashrelief='flat')
        self.content = content
        content.pack(fill='both', expand=True, padx=24)
        listing = tk.Frame(content, bg=WHITE, highlightthickness=1, highlightbackground=BORDER)
        content.add(listing, minsize=300, stretch='always')
        inspector = tk.Frame(content, bg=WHITE, width=400, highlightthickness=1, highlightbackground=BORDER)
        content.add(inspector, minsize=400, width=400, stretch='never')
        filebar = tk.Frame(listing, bg=WHITE)
        filebar.pack(fill='x', padx=15, pady=12)
        self.folder_title = self.label(filebar, 'Documents', size=12, bold=True)
        self.folder_title.pack(side='left')
        self.all_button = self.button(filebar, 'All files', lambda: self.set_filter(False))
        self.all_button.pack(side='right', padx=(6, 0))
        self.docs_button = self.button(filebar, 'Documents', lambda: self.set_filter(True))
        self.docs_button.pack(side='right')
        tree_frame = tk.Frame(listing, bg=WHITE)
        tree_frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=('name', 'type', 'size', 'modified'), show='headings', selectmode='browse')
        for name, label, width in [('name', 'Name ↑', 250), ('type', 'Type', 75), ('size', 'Size', 80), ('modified', 'Modified', 140)]:
            self.tree.heading(name, text=label, anchor='w', command=lambda n=name: self.sort_by(n))
            self.tree.column(name, width=width, minwidth=55, anchor='w', stretch=name == 'name')
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        horizontal = ttk.Scrollbar(tree_frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        horizontal.pack(side='bottom', fill='x')
        scrollbar.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        self.tree.bind('<Double-1>', self.open_selection)
        self.tree.bind('<Return>', self.open_selection)
        self.tree.tag_configure('folder', foreground='#52657f')
        footer = tk.Frame(listing, bg=WHITE)
        footer.pack(fill='x', padx=12, pady=9)
        self.count_label = self.label(footer, '', MUTED, 8)
        self.count_label.pack(side='left')
        self.button(footer, 'Next ›', lambda: self.page_move(1)).pack(side='right')
        self.button(footer, '‹ Previous', lambda: self.page_move(-1)).pack(side='right', padx=4)

        card = tk.Frame(inspector, bg=WHITE)
        card.pack(fill='x', padx=20, pady=(19, 12))
        self.label(card, 'DOCUMENT DETAILS', MUTED, 8, True).pack(anchor='w')
        title_row = tk.Frame(card, bg=WHITE)
        title_row.pack(fill='x', pady=(17, 9))
        self.file_badge = self.label(title_row, 'DOC', TEAL, 11, True, bg='#eaf5f0', width=5, pady=12)
        self.file_badge.pack(side='left', padx=(0, 12))
        self.file_title = self.label(title_row, 'Select a file', size=12, bold=True, anchor='w', justify='left', wraplength=235)
        self.file_title.pack(side='left', fill='x', expand=True)
        self.file_subtitle = self.label(card, 'Preview content and file details here.', MUTED, 8, anchor='w', justify='left', wraplength=305)
        self.file_subtitle.pack(fill='x', pady=(0, 11))
        self.identity_label = self.label(card, 'File details appear first.\n\nDocument summaries run only on request.', '#697685', 8, anchor='w', justify='left', wraplength=310)
        self.identity_label.pack(fill='x')
        identity_actions = tk.Frame(card, bg=WHITE)
        identity_actions.pack(fill='x', pady=(10, 0))
        self.button(identity_actions, 'Copy path', self.copy_path).pack(side='left')
        self.open_button = self.button(identity_actions, 'Show in folder', self.reveal)
        self.open_button.pack(side='left', padx=4)
        tk.Frame(inspector, height=1, bg=BORDER).pack(fill='x')
        tabs = tk.Frame(inspector, bg=WHITE)
        tabs.pack(fill='x', padx=16, pady=10)
        self.preview_button = self.button(tabs, 'Preview', lambda: self.switch_mode('preview'))
        self.preview_button.pack(side='left')
        self.summary_button = self.button(tabs, 'AI excerpt' if self.ai_config else 'Lightweight summary', self.request_summary)
        self.summary_button.pack(side='left', padx=5)
        self.summary_button.configure(state='disabled')
        self.cancel_button = self.button(tabs, 'Cancel', self.cancel_work)
        self.cancel_button.pack(side='right')
        self.pane_label = self.label(inspector, 'Source preview', TEAL, 8, True, anchor='w')
        self.pane_label.pack(fill='x', padx=22, pady=(0, 8))
        textframe = tk.Frame(inspector, bg=WHITE)
        textframe.pack(fill='both', expand=True, padx=(20, 9), pady=(0, 12))
        self.text = tk.Text(textframe, wrap='word', bg=WHITE, fg='#485665', relief='flat', bd=0,
                            font=self.ui.font(10), spacing1=3, spacing3=9, padx=2, cursor='arrow', state='disabled')
        self.text.tag_configure('heading', foreground=INK, font=self.ui.font(11, True), spacing1=12, spacing3=10)
        self.text.tag_configure('anchor', foreground=TEAL, font=self.ui.font(8), spacing3=13)
        self.text.tag_configure('muted', foreground=MUTED, font=self.ui.font(8))
        textscroll = ttk.Scrollbar(textframe, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=textscroll.set)
        textscroll.pack(side='right', fill='y')
        self.text.pack(fill='both', expand=True)
        self.section_bar = tk.Frame(inspector, bg='#f3f8f6')
        self.section_label = self.label(self.section_bar, '', TEAL, 8)
        self.section_label.pack(side='left', padx=10)
        self.button(self.section_bar, '‹', lambda: self.show_sections(-24)).pack(side='right')
        self.button(self.section_bar, '›', lambda: self.show_sections(24)).pack(side='right')
        self.write_text('Select a document to get started.\n\nBrowse PDF, Word, Excel, PowerPoint, HWPX, and text documents.\n\nSource code supports preview and search. Summaries are available only for documents.')
        statusbar = tk.Frame(workspace, bg=BG)
        statusbar.pack(fill='x', padx=25, pady=12)
        self.status = tk.StringVar(value='Ready')
        self.label(statusbar, '', MUTED, 8, textvariable=self.status).pack(side='left')
        self.label(statusbar, 'OFFLINE  ·  CPU ONLY', '#8a95a1', 7).pack(side='right')
        self.preview_button.configure(bg='#eaf5f0', fg=TEAL)

    def _shortcuts(self):
        self.bind('<Control-equal>', lambda event: self.change_scale(1))
        self.bind('<Control-plus>', lambda event: self.change_scale(1))
        self.bind('<Control-minus>', lambda event: self.change_scale(-1))
        self.bind('<Control-0>', lambda event: self.change_scale(reset=True))
        self.bind('<Control-f>', lambda event: self.search_entry.focus_set())
        self.bind('<Control-l>', lambda event: (self.path_entry.focus_set(), self.path_entry.select_range(0, 'end')))
        self.bind('<Alt-Left>', lambda event: self.back())
        self.bind('<Alt-Up>', lambda event: self.up())
        self.bind('<F5>', lambda event: self.refresh())
        self.bind('<Escape>', lambda event: self.cancel_work())

    def load_settings(self):
        try:
            return json.loads((self.state_dir / 'settings.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def change_scale(self, direction=0, reset=False):
        choices = UiScale.CHOICES[1:]
        if reset:
            self.scale_var.set('Auto')
        elif direction:
            current = '100%' if self.scale_var.get() == 'Auto' else self.scale_var.get()
            self.scale_var.set(choices[max(0, min(len(choices) - 1, choices.index(current) + direction))])
        self.ui.apply(self.scale_var.get())
        self.after_idle(self._adapt_layout)
        self.save_settings()

    def _window_resized(self, event):
        if event.widget is self:
            self._adapt_layout()

    def _adapt_layout(self):
        # Compact windows keep the inspector usable; folder navigation remains
        # available through the address bar and the toolbar's Open button.
        compact = self.winfo_width() < self.ui.px(1080)
        self.scale_label.configure(text='UI scale (fit)' if self.ui.fit_limited else 'UI scale')
        if compact and self.sidebar.winfo_manager() == 'pack':
            self.sidebar.pack_forget()
        elif not compact and self.sidebar.winfo_manager() != 'pack':
            self.sidebar.pack(side='left', fill='y', before=self.workspace)

    def save_settings(self):
        try:
            (self.state_dir / 'settings.json').write_text(json.dumps({
                'folder': str(self.folder), 'ui_scale': self.scale_var.get()}, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    def choose_folder(self):
        folder = filedialog.askdirectory(title='Choose a folder to explore', initialdir=str(getattr(self, 'folder', Path.home())))
        if folder:
            self.navigate(folder)

    def navigate(self, folder, history=True, recursive=False):
        try:
            folder = Path(folder).expanduser().resolve()
            valid = folder.is_dir()
        except OSError:
            valid = False
        if not valid:
            self.status.set('Folder not found: ' + str(folder))
            return
        self.worker.stop()
        self.clear_summary_state()
        self.scan_cancel.set()
        self.view_id += 1
        self.folder = folder
        self.snapshot = self.state_dir / ('listing-%s.db' % self.view_id)
        self.path_var.set(str(folder))
        self.folder_title.configure(text=folder.name or str(folder))
        if history:
            self.history = self.history[:self.history_position + 1] + [folder]
            self.history = self.history[-32:]
            self.history_position = len(self.history) - 1
        self.search_var.set('')
        self.offset = 0
        self.searching = self.search_results = False
        self.selected = self.kind = self.summary_result = None
        self.summary_button.configure(state='disabled')
        self.section_bar.pack_forget()
        self.file_title.configure(text='Select a file')
        self.file_subtitle.configure(text=str(folder))
        self.identity_label.configure(text='Source files are left unchanged.\nSelect a file to view its details.')
        self.write_text('Select a document to view its content and details.')
        self.tree.delete(*self.tree.get_children())
        self.start_scan(recursive)

    def start_scan(self, recursive=False):
        self.scan_cancel.set()
        cancel = threading.Event()
        self.scan_cancel = cancel
        view_id, filename, folder = self.view_id, self.snapshot, self.folder
        self.ready, self.scan_running = False, True
        self.status.set('Preparing to search subfolders…' if recursive else 'Reading folder…')

        def publish(done=False, count=0, error=None):
            try:
                self.scan_events.put_nowait((view_id, done, count, error))
            except queue.Full:
                if done:
                    try:
                        self.scan_events.get_nowait()
                        self.scan_events.put_nowait((view_id, done, count, error))
                    except (queue.Empty, queue.Full):
                        pass

        try:
            self.scan_requests.get_nowait()
        except queue.Empty:
            pass
        self.scan_requests.put_nowait((folder, filename, recursive, cancel, publish))

    def scan_loop(self):
        while not self.scan_shutdown.is_set():
            try:
                folder, filename, recursive, cancel, publish = self.scan_requests.get(timeout=.2)
            except queue.Empty:
                continue
            if cancel.is_set():
                continue
            try:
                count = scan(folder, filename, recursive, cancel.is_set, lambda n: publish(count=n))
                publish(True, count)
            except Exception as error:
                publish(True, error=str(error))
            # Keep a bounded number of snapshots. No user files are removed.
            snapshots = sorted(self.state_dir.glob('listing-*.db'), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in snapshots[3:]:
                for suffix in ('', '-wal', '-shm'):
                    try:
                        Path(str(old) + suffix).unlink(missing_ok=True)
                    except OSError:
                        pass

    def back(self):
        if self.history_position > 0:
            self.history_position -= 1
            self.navigate(self.history[self.history_position], history=False)

    def up(self):
        self.navigate(self.folder.parent)

    def refresh(self):
        self.navigate(self.folder, history=False)

    def search_changed(self, event):
        if event.keysym in ('Return', 'Escape') or self.search_results:
            return
        if self.debounce:
            self.after_cancel(self.debounce)
        if self.search_mode.get() == 'Name / path' and not self.recursive.get():
            self.debounce = self.after(180, self.filter_changed)

    def filter_changed(self):
        self.debounce = None
        self.offset = 0
        self.render_files()

    def search(self):
        query = self.search_var.get().strip()
        if not query:
            if self.search_results:
                self.refresh()
            else:
                self.filter_changed()
            return
        if self.search_mode.get() == 'File contents':
            self.scan_cancel.set()
            self.worker.stop()
            self.search_results = self.searching = True
            self.matches = {}
            self.tree.delete(*self.tree.get_children())
            self.summary_button.configure(state='disabled')
            self.status.set('Searching file contents… Select a file to stop searching and open its preview.')
            self.worker.start(action='search', path=str(self.folder), query=query, recursive=self.recursive.get(), search_db=str(self.state_dir / 'content-search.db'), memory_mb=self.profile.worker_mb)
        else:
            self.search_results = self.searching = False
            self.offset = 0
            if self.recursive.get():
                # A new disk snapshot prevents overlap with a cancelled scan.
                self.view_id += 1
                self.snapshot = self.state_dir / ('listing-%s.db' % self.view_id)
                self.start_scan(True)
            else:
                self.render_files()

    def set_filter(self, value):
        self.document_filter, self.offset = value, 0
        self.docs_button.configure(bg='#eaf5f0' if value else WHITE, fg=TEAL if value else INK)
        self.all_button.configure(bg=WHITE if value else '#eaf5f0', fg=INK if value else TEAL)
        if not self.search_results:
            self.render_files()
        self.status.set('Document candidates are filtered by extension. Actual formats are validated on selection.' if value else 'Showing all files')

    def sort_by(self, column):
        key = {'name': 'name', 'type': 'extension', 'size': 'size', 'modified': 'modified'}[column]
        self.descending = not self.descending if self.sort == key else False
        self.sort = key
        for name, label in [('name', 'Name'), ('type', 'Type'), ('size', 'Size'), ('modified', 'Modified')]:
            self.tree.heading(name, text=label + (' ↓' if self.descending else ' ↑') if name == column else label)
        if not self.search_results:
            self.render_files()

    def render_files(self):
        if not self.ready or self.search_results:
            return
        selection = self.selected
        try:
            rows, self.total = page(self.snapshot, self.search_var.get().strip(), self.offset,
                                    self.document_filter, self.sort, self.descending)
        except (OSError, sqlite3.Error) as error:
            self.status.set('Unable to read the file list: ' + str(error))
            return
        self.tree.delete(*self.tree.get_children())
        for path, name, directory, size, modified, extension in rows:
            prefix = '▸  ' if directory else '▤  ' if extension in ('.pdf', '.docx', '.txt', '.md', '.hwpx') else '▧  ' if extension in ('.xlsx', '.pptx') else '·  '
            self.tree.insert('', 'end', iid=path, values=(prefix + name, 'Folder' if directory else extension[1:].upper() or 'File',
                                                         '—' if directory else size_label(size), date_label(modified)),
                             tags=('folder',) if directory else ())
        if selection and self.tree.exists(str(selection)):
            self.tree.selection_set(str(selection))
        self.count_label.configure(text='%s items  ·  %s–%s' % (format(self.total, ','), self.offset + 1 if rows else 0, self.offset + len(rows)))

    def page_move(self, delta):
        if self.search_results:
            return
        new = self.offset + PAGE_SIZE * delta
        if 0 <= new < self.total:
            self.offset = new
            self.render_files()

    def selection_changed(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        path = Path(selected[0])
        if self.selected == path:
            return
        if self.searching:
            self.searching = False
            self.status.set('Content search stopped. Showing the selected file.')
        self.worker.stop()
        self.clear_summary_state()
        self.selected, self.kind = path, None
        self.summary_result = None
        self.fallback_result = None
        self.summary_offset = 0
        self.section_bar.pack_forget()
        self.summary_button.configure(state='disabled', text='AI excerpt' if self.ai_config else 'Lightweight summary')
        self.file_title.configure(text=path.name)
        self.file_subtitle.configure(text=str(path))
        self.info = {}
        self.mode = 'preview'
        try:
            stat = path.stat()
            self.selected_stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
            self.basic_identity = 'Size   %s\nModified   %s\nCreated   %s' % (size_label(stat.st_size), date_label(stat.st_mtime), date_label(getattr(stat, 'st_birthtime', stat.st_ctime)))
            self.identity_label.configure(text=self.basic_identity + '\nType   Checking…')
            if path.is_dir():
                self.file_badge.configure(text='DIR')
                self.identity_label.configure(text=self.basic_identity + '\nType   Folder')
                self.preview_text = 'Double-click a folder to open it.'
                self.switch_mode('preview')
                return
            self.file_badge.configure(text=(path.suffix[1:].upper() or 'FILE')[:5])
            self.preview_text = 'Checking the actual file format and parser availability…'
            self.switch_mode('preview')
            self.worker.start(action='inspect', path=str(path), memory_mb=self.profile.worker_mb)
            self.status.set('Validating file format and preparing preview…')
        except OSError as error:
            self.write_text(str(error))

    def open_selection(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        path = Path(selected[0])
        if path.is_dir():
            self.navigate(path)
        elif self.kind and self.kind.get('document') and self.kind.get('parser'):
            if os.name == 'nt':
                os.startfile(str(path))
            else:
                subprocess.Popen(['xdg-open', str(path)])

    def copy_path(self):
        if self.selected:
            self.clipboard_clear()
            self.clipboard_append(str(self.selected))
            self.status.set('Full path copied.')

    def reveal(self):
        if self.selected and os.name == 'nt':
            subprocess.Popen(['explorer.exe', '/select,', str(self.selected)])

    def write_text(self, content):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('end', content)
        self.text.configure(state='disabled')

    def switch_mode(self, mode):
        self.mode = mode
        self.preview_button.configure(bg='#eaf5f0' if mode == 'preview' else WHITE, fg=TEAL if mode == 'preview' else INK)
        self.summary_button.configure(bg='#eaf5f0' if mode == 'summary' else WHITE, fg=TEAL if mode == 'summary' else INK)
        if mode == 'preview':
            self.pane_label.configure(text='Source preview · Up to 24,000 characters')
            self.section_bar.pack_forget()
            self.write_text(self.preview_text)
        elif self.summary_result:
            self.display_summary(self.summary_result['bullets'], complete=True)

    def file_unchanged(self):
        try:
            stat = self.selected.stat()
            return self.selected_stamp == (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
        except (OSError, AttributeError):
            return False

    def request_summary(self):
        if not self.selected or not self.kind or not self.kind.get('document') or not self.kind.get('parser'):
            return
        if not self.file_unchanged():
            self.summary_button.configure(state='disabled')
            self.status.set('The file has changed since selection. Refresh and select it again.')
            return
        self.worker.stop()
        self.clear_summary_state()
        self.summary_result = None
        self.fallback_result = None
        self.summary_offset = 0
        try:
            self.summary_workspace = tempfile.TemporaryDirectory(prefix='summary-', dir=self.state_dir)
        except OSError as error:
            self.status.set('Unable to create temporary workspace. Check available disk space: ' + str(error)[:150])
            return
        self.summary_state = Path(self.summary_workspace.name) / 'working.db'
        self.switch_mode('summary')
        self.section_bar.pack_forget()
        self.write_text('Preparing a lightweight summary.\n\nProcessing document sections while preserving source sentences and locations.')
        self.pane_label.configure(text='Lightweight Summary · Processing')
        self.summary_button.configure(state='disabled')
        self.worker.start(action='summary', path=str(self.selected), workspace=str(self.summary_state), memory_mb=self.profile.worker_mb)
        self.status.set('Summarizing document… Select another file or press Esc to cancel.')

    def display_summary(self, bullets, complete=False, detail=False):
        self.mode = 'summary'
        is_ai = complete and self.summary_result and self.summary_result.get('mode') == 'ai' and not detail
        structured = self.kind and self.kind.get('format') == 'xlsx'
        ai_label = 'AI selection · Structured data / Complete' if structured else 'AI selection · Verbatim source / Complete'
        self.pane_label.configure(text='Source evidence by section' if detail else ai_label if is_ai else 'Lightweight Summary · Complete' if complete else 'Quick Summary · Preliminary / processing')
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        header = '%s\n%s\n%s\nModified: %s\n' % (self.selected.name, self.kind.get('label', 'Unknown'), self.selected, date_label(self.selected.stat().st_mtime) if self.selected.exists() else 'Unknown')
        self.text.insert('end', header + '\n', 'muted')
        if self.summary_result:
            self.text.insert('end', '%s · %s · %s\n\n' % (self.info.get('count', 'Unknown'), self.info.get('category', 'Unknown'), self.info.get('language', 'Unknown')), 'muted')
        if detail:
            for bullet in bullets:
                self.text.insert('end', bullet['section'] + '\n', 'heading')
                self.text.insert('end', bullet['text'] + '\n')
                self.text.insert('end', '[%s]\n' % bullet['anchor'], 'anchor')
        else:
            result = self.summary_result if complete else None
            selected = bullets[0] if result and result.get('summary_text') else extractive_sentence(bullets)
            sentence = result['summary_text'] if result and result.get('summary_text') else selected['text'] if selected else None
            self.text.insert('end', 'One-line summary · Extracted data\n' if structured else 'One-line summary · Source excerpt\n', 'heading')
            self.text.insert('end', (sentence or 'Identifying the main points in the document.') + '\n', 'summary_result')
            if selected:
                self.text.insert('end', '\nSource: %s\n' % selected['anchor'], 'anchor')
            if is_ai:
                self.text.insert('end', 'AI only selects a sentence. Check its relevance against the source.\n', 'muted')
            if structured:
                self.text.insert('end', 'Spreadsheet text is extracted programmatically from cells, ranges, and formulas.\n', 'muted')
        if complete:
            result = self.summary_result
            count = result.get('sections', 0) if result else len(bullets)
            self.text.insert('end', '\nUse the arrows below to review source evidence for each section.', 'muted')
            if result and result.get('empty_pages'):
                self.text.insert('end', '\n%s pages without text were not summarized. OCR may be required.' % result['empty_pages'], 'muted')
            self.section_label.configure(text='%s sections · All evidence' % count)
            self.section_bar.pack(side='bottom', fill='x')
        self.text.configure(state='disabled')

    def show_sections(self, delta):
        if not self.summary_result or not self.file_unchanged():
            self.status.set('The source has changed or no summary is available. Select the file again.')
            return
        count = self.summary_result['sections']
        offset = self.summary_offset + delta
        if offset < 0:
            offset = 0
        if offset >= count:
            return
        self.summary_offset = offset
        self.worker.start(action='sections', path=str(self.selected), workspace=str(self.summary_state), key=self.summary_result['key'], offset=offset,
                          memory_mb=self.profile.worker_mb)

    def cancel_work(self):
        self.worker.stop()
        self.clear_summary_state()
        self.summary_result = None
        self.fallback_result = None
        self.section_bar.pack_forget()
        self.scan_cancel.set()
        self.scan_running = self.searching = False
        if self.mode == 'summary' and not self.summary_result:
            self.pane_label.configure(text='Lightweight Summary · Cancelled / incomplete')
        if self.kind:
            self.summary_button.configure(state='normal' if self.kind.get('document') and self.kind.get('parser') else 'disabled')
        self.status.set('Operation cancelled. You can continue browsing files.')

    def poll(self):
        try:
            for _ in range(4):
                try:
                    view_id, done, count, error = self.scan_events.get_nowait()
                except queue.Empty:
                    break
                if view_id != self.view_id:
                    continue
                self.ready = True
                self.scan_running = not done
                self.render_files()
                self.status.set(('Unable to read folder: ' + error) if error else ('%s items · Ready' if done else '%s items found · Scanning…') % format(count, ','))
            for event in self.worker.drain():
                self.handle_event(event)
        except Exception as error:
            self.status.set('Processing error: ' + str(error)[:150])
        self.after(60, self.poll)

    def handle_event(self, event):
        name = event['event']
        if name == 'progress':
            self.status.set(event['message'])
            return
        if name == 'match':
            path = event['path']
            if not self.tree.exists(path):
                self.matches[path] = event
                self.tree.insert('', 'end', iid=path, values=('▤  ' + event['name'], event['extension'][1:].upper(), size_label(event['size']), date_label(event['modified'])))
                self.count_label.configure(text='%s matches · Searching contents' % len(self.matches))
            return
        if name == 'search_done':
            self.searching = False
            self.count_label.configure(text='%s matches · %s files checked' % (event['matches'], event['scanned']))
            self.status.set('Search complete' + (' · Showing the first 160 results. Refine your search.' if event['limited'] else ''))
            return
        if name == 'error':
            self.searching = False
            if self.worker.action == 'ai' and self.fallback_result:
                self.summary_result = self.fallback_result
                self.summary_button.configure(state='normal')
                self.display_summary(self.summary_result['bullets'], complete=True)
                self.status.set('Using a lightweight summary: ' + event['message'])
                return
            if self.worker.action == 'summary':
                self.worker.stop()
                self.clear_summary_state()
            self.status.set(event['message'])
            if self.mode == 'summary':
                self.pane_label.configure(text='Lightweight Summary · Incomplete')
            elif not self.kind:
                self.write_text(event['message'])
                self.identity_label.configure(text=getattr(self, 'basic_identity', '') + '\nType   Validation failed / Summary unavailable')
            if self.kind:
                self.summary_button.configure(state='normal' if self.kind.get('document') and self.kind.get('parser') else 'disabled')
            return
        if not self.selected or not self.file_unchanged():
            self.summary_button.configure(state='disabled')
            self.status.set('The file changed during processing. Results were discarded.')
            return
        if name == 'inspected':
            self.kind, self.info, self.preview_text = event['kind'], event['info'], event['preview']
            enabled = self.kind['document'] and self.kind['parser']
            self.summary_button.configure(state='normal' if enabled else 'disabled')
            self.file_subtitle.configure(text=self.kind['label'] + '\n' + str(self.selected))
            identity = self.basic_identity + '\nType   ' + self.kind['label']
            identity += '\nTitle   %s\nLength   %s\nLanguage   %s\nCategory   %s' % tuple(self.info.get(k, 'Unknown') for k in ('title', 'count', 'language', 'category'))
            self.identity_label.configure(text=identity)
            if not self.preview_text:
                self.preview_text = self.kind['reason'] or 'A safe text preview is unavailable for this file.'
            if str(self.selected) in self.matches:
                match = self.matches[str(self.selected)]
                self.preview_text = 'Search match [%s]\n%s\n\n──────────\n\n%s' % (match['anchor'], match['snippet'], self.preview_text)
            self.switch_mode('preview')
            self.status.set('Document validated · Summary available' if enabled else self.kind['reason'] or 'Preview ready')
        elif name == 'quick':
            if self.mode == 'summary':
                self.display_summary(event['bullets'])
        elif name == 'summary':
            self.info.update(event['info'])
            self.fallback_result = event
            if self.ai_config and profile().available >= 1280 * 1024**2:
                self.display_summary(event['bullets'], complete=False)
                self.pane_label.configure(text='Quick Summary · AI selecting a source sentence')
                self.worker.start(action='ai', path=str(self.selected), workspace=str(self.summary_state), key=event['key'],
                                  content_hash=event['source']['content_hash'], memory_mb=768)
                return
            self.summary_result = event
            self.summary_button.configure(state='normal')
            self.display_summary(event['bullets'], complete=True)
            self.status.set('Low available memory. Using a lightweight summary.' if self.ai_config else 'Source reread and summarized · Results retained only for the current selection')
        elif name == 'ai_summary':
            self.summary_result = dict(self.fallback_result, **{k: v for k, v in event.items() if k != 'event'})
            self.summary_button.configure(state='normal')
            self.display_summary(self.summary_result['bullets'], complete=True)
            self.status.set(('AI source selection complete' if event['mode'] == 'ai' else 'Using a source sentence instead') + ' · %.1fs · Model unloaded · No cache' % event['total_ai_seconds'])
        elif name == 'sections':
            self.display_summary(event['bullets'], complete=True, detail=True)
            count = self.summary_result['sections']
            self.section_label.configure(text='%s–%s / %s sections' % (event['offset'] + 1, min(count, event['offset'] + 24), count))

    def clear_summary_state(self):
        self.fallback_result = None
        if self.summary_workspace:
            self.summary_workspace.cleanup()
            self.summary_workspace = None
            self.summary_state = None

    def close(self):
        self.scan_shutdown.set()
        self.scan_cancel.set()
        self.worker.stop()
        self.clear_summary_state()
        self.save_settings()
        self.destroy()


def main():
    parser = argparse.ArgumentParser(description='Local document explorer')
    parser.add_argument('folder', nargs='?')
    parser.add_argument('--state-dir')
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--no-ai', action='store_true', help='Use extractive summaries without loading a model')
    args = parser.parse_args()
    app = Explorer(args.folder, args.state_dir, ai_enabled=not args.no_ai)
    if args.smoke:
        app.after(1800, app.close)
    app.mainloop()


if __name__ == '__main__':
    main()
