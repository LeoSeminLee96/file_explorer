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

BASE = Path(__file__).resolve().parent
BG, WHITE, INK, MUTED, BORDER, TEAL = '#f7f8fa', '#ffffff', '#202b38', '#7a8494', '#e7eaf0', '#087f73'
FONT = '맑은 고딕' if os.name == 'nt' else 'DejaVu Sans'


def size_label(size):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return ('%d %s' if unit == 'B' else '%.1f %s') % (size, unit)
        size /= 1024


def date_label(value):
    return datetime.fromtimestamp(value).strftime('%Y.%m.%d  %H:%M')


class Explorer(tk.Tk):
    def __init__(self, folder=None, state_dir=None, ai_enabled=True):
        super().__init__()
        self.title('문서함 · Document Explorer')
        self.geometry('1400x900')
        self.minsize(1120, 740)
        self.configure(bg=BG)
        self.option_add('*Font', (FONT, 10))
        self.state_dir = Path(state_dir or BASE / '.data')
        self.state_dir.mkdir(parents=True, exist_ok=True)
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
        self._shortcuts()
        self.protocol('WM_DELETE_WINDOW', self.close)
        settings = self.load_settings()
        initial = folder or settings.get('folder') or str(BASE / 'sample_documents')
        if not Path(initial).is_dir():
            initial = str(BASE)
        self.navigate(initial)
        self.after(60, self.poll)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('Treeview', background=WHITE, fieldbackground=WHITE, foreground=INK,
                        font=(FONT, 10), rowheight=43, borderwidth=0)
        style.configure('Treeview.Heading', background='#f8f9fb', foreground=MUTED,
                        relief='flat', borderwidth=0, padding=(12, 12), font=(FONT, 9))
        style.map('Treeview', background=[('selected', '#e6f3ef')], foreground=[('selected', '#075d55')])
        style.map('Treeview.Heading', background=[('active', '#eef1f5')])
        style.configure('Vertical.TScrollbar', arrowsize=12, background='#dde2e8', troughcolor=WHITE, borderwidth=0)

    def label(self, parent, text='', color=INK, size=10, bold=False, bg=None, **kwargs):
        return tk.Label(parent, text=text, fg=color, bg=bg or parent.cget('bg'), font=(FONT, size, 'bold' if bold else 'normal'), **kwargs)

    def button(self, parent, text, command, primary=False, **kwargs):
        return tk.Button(parent, text=text, command=command, bg=TEAL if primary else WHITE,
                         fg=WHITE if primary else INK, activebackground='#09695f' if primary else '#eef2f5',
                         activeforeground=WHITE if primary else INK, relief='flat', bd=0, cursor='hand2',
                         padx=14, pady=8, disabledforeground='#b4bbc4', **kwargs)

    def _build(self):
        sidebar = tk.Frame(self, bg='#eef1f5', width=210)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg='#eef1f5')
        brand.pack(fill='x', padx=22, pady=(29, 35))
        self.label(brand, '▤', TEAL, 27, True).pack(side='left', padx=(0, 10))
        names = tk.Frame(brand, bg='#eef1f5')
        names.pack(side='left')
        self.label(names, '문서함', size=19, bold=True).pack(anchor='w')
        self.label(names, 'DOCUMENT EXPLORER', MUTED, 7).pack(anchor='w', pady=(3, 0))
        self.button(sidebar, '+  폴더 열기', self.choose_folder, True).pack(fill='x', padx=19, pady=(0, 30))
        self.label(sidebar, '라이브러리', MUTED, 8, bold=True).pack(anchor='w', padx=24, pady=(0, 12))
        locations = [('▦   샘플 문서', BASE / 'sample_documents'), ('⌂   내 문서', Path.home() / 'Documents'),
                     ('▣   바탕 화면', Path.home() / 'Desktop'), ('↓   다운로드', Path.home() / 'Downloads'),
                     ('‹/›   프로젝트', BASE), ('⌂   사용자 폴더', Path.home())]
        for name, path in locations:
            button = self.button(sidebar, name, lambda p=path: self.navigate(p), anchor='w')
            button.configure(bg='#eef1f5', pady=11)
            button.pack(fill='x', padx=12, pady=2)
        self.label(sidebar, '작업 방식', MUTED, 8, bold=True).pack(anchor='w', padx=24, pady=(29, 14))
        for text in ('✓  파일은 이 PC에만', '✓  모델 없이 검색·미리보기', '✓  요청할 때만 문서 요약'):
            self.label(sidebar, text, '#647384', 9).pack(anchor='w', padx=23, pady=7)
        bottom = tk.Frame(sidebar, bg='#e4e9ef')
        bottom.pack(side='bottom', fill='x', padx=16, pady=20)
        self.label(bottom, '●  저메모리 설계', TEAL, 9, True).pack(anchor='w', padx=12, pady=(13, 5))
        self.label(bottom, '%s · 파서 1개' % self.profile.name, '#687583', 8).pack(anchor='w', padx=12, pady=(0, 12))

        workspace = tk.Frame(self, bg=BG)
        workspace.pack(side='left', fill='both', expand=True)
        header = tk.Frame(workspace, bg=WHITE, height=92)
        header.pack(fill='x')
        header.pack_propagate(False)
        heading = tk.Frame(header, bg=WHITE)
        heading.pack(side='left', padx=28, pady=18)
        self.label(heading, '내 문서 탐색', size=20, bold=True).pack(anchor='w')
        self.label(heading, '찾고, 살펴보고, 핵심만 읽으세요.', MUTED, 9).pack(anchor='w', pady=(5, 0))
        self.label(header, '●  LOCAL WORKSPACE', TEAL, 8, True, bg='#edf7f3', padx=14, pady=8).pack(side='right', padx=26)
        tk.Frame(workspace, height=1, bg=BORDER).pack(fill='x')
        toolbar = tk.Frame(workspace, bg=BG)
        toolbar.pack(fill='x', padx=24, pady=(20, 12))
        self.button(toolbar, '←', self.back).pack(side='left', padx=(0, 5))
        self.button(toolbar, '↑', self.up).pack(side='left', padx=(0, 8))
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
        self.search_mode = tk.StringVar(value='이름·경로')
        selector = ttk.Combobox(searchbar, textvariable=self.search_mode, state='readonly',
                                values=('이름·경로', '문서·코드 본문'), width=15)
        selector.pack(side='left', padx=(10, 8), ipady=9)
        self.recursive = tk.BooleanVar(value=False)
        tk.Checkbutton(searchbar, text='하위 폴더', variable=self.recursive, bg=BG, fg='#687583',
                       activebackground=BG, selectcolor=WHITE).pack(side='left', padx=5)
        self.button(searchbar, '검색', self.search, True).pack(side='left', padx=(5, 0))

        content = tk.PanedWindow(workspace, orient='horizontal', bg=BG, sashwidth=14, bd=0, sashrelief='flat')
        content.pack(fill='both', expand=True, padx=24)
        listing = tk.Frame(content, bg=WHITE, highlightthickness=1, highlightbackground=BORDER)
        content.add(listing, minsize=380, stretch='always')
        inspector = tk.Frame(content, bg=WHITE, width=365, highlightthickness=1, highlightbackground=BORDER)
        content.add(inspector, minsize=325, width=365, stretch='never')
        filebar = tk.Frame(listing, bg=WHITE)
        filebar.pack(fill='x', padx=15, pady=12)
        self.folder_title = self.label(filebar, '문서', size=12, bold=True)
        self.folder_title.pack(side='left')
        self.all_button = self.button(filebar, '전체 파일', lambda: self.set_filter(False))
        self.all_button.pack(side='right', padx=(6, 0))
        self.docs_button = self.button(filebar, '문서 후보', lambda: self.set_filter(True))
        self.docs_button.pack(side='right')
        tree_frame = tk.Frame(listing, bg=WHITE)
        tree_frame.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tree_frame, columns=('name', 'type', 'size', 'modified'), show='headings', selectmode='browse')
        for name, label, width in [('name', '이름 ↑', 250), ('type', '형식', 75), ('size', '크기', 80), ('modified', '수정한 날짜', 140)]:
            self.tree.heading(name, text=label, anchor='w', command=lambda n=name: self.sort_by(n))
            self.tree.column(name, width=width, minwidth=55, anchor='w', stretch=name == 'name')
        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
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
        self.button(footer, '다음 ›', lambda: self.page_move(1)).pack(side='right')
        self.button(footer, '‹ 이전', lambda: self.page_move(-1)).pack(side='right', padx=4)

        card = tk.Frame(inspector, bg=WHITE)
        card.pack(fill='x', padx=20, pady=(19, 12))
        self.label(card, 'DOCUMENT DETAILS', MUTED, 8, True).pack(anchor='w')
        title_row = tk.Frame(card, bg=WHITE)
        title_row.pack(fill='x', pady=(17, 9))
        self.file_badge = self.label(title_row, 'DOC', TEAL, 11, True, bg='#eaf5f0', width=5, pady=12)
        self.file_badge.pack(side='left', padx=(0, 12))
        self.file_title = self.label(title_row, '파일을 선택하세요', size=12, bold=True, anchor='w', justify='left', wraplength=235)
        self.file_title.pack(side='left', fill='x', expand=True)
        self.file_subtitle = self.label(card, '미리보기와 문서 정보를 이곳에서 확인합니다.', MUTED, 8, anchor='w', justify='left', wraplength=305)
        self.file_subtitle.pack(fill='x', pady=(0, 11))
        self.identity_label = self.label(card, '파일 정보가 먼저 표시됩니다.\n\n문서 요약은 요청할 때만 실행됩니다.', '#697685', 8, anchor='w', justify='left', wraplength=310)
        self.identity_label.pack(fill='x')
        identity_actions = tk.Frame(card, bg=WHITE)
        identity_actions.pack(fill='x', pady=(10, 0))
        self.button(identity_actions, '경로 복사', self.copy_path).pack(side='left')
        self.open_button = self.button(identity_actions, '폴더에서 보기', self.reveal)
        self.open_button.pack(side='left', padx=4)
        tk.Frame(inspector, height=1, bg=BORDER).pack(fill='x')
        tabs = tk.Frame(inspector, bg=WHITE)
        tabs.pack(fill='x', padx=16, pady=10)
        self.preview_button = self.button(tabs, '미리보기', lambda: self.switch_mode('preview'))
        self.preview_button.pack(side='left')
        self.summary_button = self.button(tabs, 'AI 원문 선택' if self.ai_config else '경량 요약', self.request_summary)
        self.summary_button.pack(side='left', padx=5)
        self.summary_button.configure(state='disabled')
        self.cancel_button = self.button(tabs, '중단', self.cancel_work)
        self.cancel_button.pack(side='right')
        self.pane_label = self.label(inspector, '원문 미리보기', TEAL, 8, True, anchor='w')
        self.pane_label.pack(fill='x', padx=22, pady=(0, 8))
        textframe = tk.Frame(inspector, bg=WHITE)
        textframe.pack(fill='both', expand=True, padx=(20, 9), pady=(0, 12))
        self.text = tk.Text(textframe, wrap='word', bg=WHITE, fg='#485665', relief='flat', bd=0,
                            font=(FONT, 10), spacing1=3, spacing3=9, padx=2, cursor='arrow', state='disabled')
        self.text.tag_configure('heading', foreground=INK, font=(FONT, 11, 'bold'), spacing1=12, spacing3=10)
        self.text.tag_configure('anchor', foreground=TEAL, font=(FONT, 8), spacing3=13)
        self.text.tag_configure('muted', foreground=MUTED, font=(FONT, 8))
        textscroll = ttk.Scrollbar(textframe, orient='vertical', command=self.text.yview)
        self.text.configure(yscrollcommand=textscroll.set)
        textscroll.pack(side='right', fill='y')
        self.text.pack(fill='both', expand=True)
        self.section_bar = tk.Frame(inspector, bg='#f3f8f6')
        self.section_label = self.label(self.section_bar, '', TEAL, 8)
        self.section_label.pack(side='left', padx=10)
        self.button(self.section_bar, '‹', lambda: self.show_sections(-24)).pack(side='right')
        self.button(self.section_bar, '›', lambda: self.show_sections(24)).pack(side='right')
        self.write_text('필요한 문서를 한 번 클릭하세요.\n\nPDF, Word, Excel, PowerPoint, HWPX와 텍스트 문서를 살펴볼 수 있습니다.\n\n코드는 미리보기와 검색만 제공하고, 문서에만 경량 요약을 제공합니다.')
        statusbar = tk.Frame(workspace, bg=BG)
        statusbar.pack(fill='x', padx=25, pady=12)
        self.status = tk.StringVar(value='준비됨')
        self.label(statusbar, '', MUTED, 8, textvariable=self.status).pack(side='left')
        self.label(statusbar, 'OFFLINE  ·  CPU ONLY', '#8a95a1', 7).pack(side='right')
        self.preview_button.configure(bg='#eaf5f0', fg=TEAL)

    def _shortcuts(self):
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

    def choose_folder(self):
        folder = filedialog.askdirectory(title='탐색할 폴더 선택', initialdir=str(getattr(self, 'folder', Path.home())))
        if folder:
            self.navigate(folder)

    def navigate(self, folder, history=True, recursive=False):
        try:
            folder = Path(folder).expanduser().resolve()
            valid = folder.is_dir()
        except OSError:
            valid = False
        if not valid:
            self.status.set('폴더를 찾을 수 없습니다: ' + str(folder))
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
        self.file_title.configure(text='파일을 선택하세요')
        self.file_subtitle.configure(text=str(folder))
        self.identity_label.configure(text='원본 파일은 변경하지 않습니다.\n파일을 선택하면 상세 정보를 표시합니다.')
        self.write_text('문서를 선택하면 원문과 문서 정보를 표시합니다.')
        self.tree.delete(*self.tree.get_children())
        self.start_scan(recursive)

    def start_scan(self, recursive=False):
        self.scan_cancel.set()
        cancel = threading.Event()
        self.scan_cancel = cancel
        view_id, filename, folder = self.view_id, self.snapshot, self.folder
        self.ready, self.scan_running = False, True
        self.status.set('하위 폴더를 포함해 검색 준비 중…' if recursive else '폴더 읽는 중…')

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
        if self.search_mode.get() == '이름·경로' and not self.recursive.get():
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
        if self.search_mode.get() == '문서·코드 본문':
            self.scan_cancel.set()
            self.worker.stop()
            self.search_results = self.searching = True
            self.matches = {}
            self.tree.delete(*self.tree.get_children())
            self.summary_button.configure(state='disabled')
            self.status.set('본문 검색 중… 파일을 선택하면 검색을 중단하고 미리보기를 엽니다.')
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
        self.status.set('문서 후보는 확장자 필터입니다. 실제 형식은 파일 선택 시 검증합니다.' if value else '전체 파일 표시')

    def sort_by(self, column):
        key = {'name': 'name', 'type': 'extension', 'size': 'size', 'modified': 'modified'}[column]
        self.descending = not self.descending if self.sort == key else False
        self.sort = key
        for name, label in [('name', '이름'), ('type', '형식'), ('size', '크기'), ('modified', '수정한 날짜')]:
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
            self.status.set('목록을 읽을 수 없습니다: ' + str(error))
            return
        self.tree.delete(*self.tree.get_children())
        for path, name, directory, size, modified, extension in rows:
            prefix = '▸  ' if directory else '▤  ' if extension in ('.pdf', '.docx', '.txt', '.md', '.hwpx') else '▧  ' if extension in ('.xlsx', '.pptx') else '·  '
            self.tree.insert('', 'end', iid=path, values=(prefix + name, '폴더' if directory else extension[1:].upper() or '파일',
                                                         '—' if directory else size_label(size), date_label(modified)),
                             tags=('folder',) if directory else ())
        if selection and self.tree.exists(str(selection)):
            self.tree.selection_set(str(selection))
        self.count_label.configure(text='%s개 항목  ·  %s–%s' % (format(self.total, ','), self.offset + 1 if rows else 0, self.offset + len(rows)))

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
            self.status.set('본문 검색을 중단하고 선택한 파일을 표시합니다.')
        self.worker.stop()
        self.clear_summary_state()
        self.selected, self.kind = path, None
        self.summary_result = None
        self.fallback_result = None
        self.summary_offset = 0
        self.section_bar.pack_forget()
        self.summary_button.configure(state='disabled', text='AI 원문 선택' if self.ai_config else '경량 요약')
        self.file_title.configure(text=path.name)
        self.file_subtitle.configure(text=str(path))
        self.info = {}
        self.mode = 'preview'
        try:
            stat = path.stat()
            self.selected_stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
            self.basic_identity = '크기   %s\n수정   %s\n생성   %s' % (size_label(stat.st_size), date_label(stat.st_mtime), date_label(getattr(stat, 'st_birthtime', stat.st_ctime)))
            self.identity_label.configure(text=self.basic_identity + '\n유형   확인 중…')
            if path.is_dir():
                self.file_badge.configure(text='DIR')
                self.identity_label.configure(text=self.basic_identity + '\n유형   폴더')
                self.preview_text = '폴더를 두 번 클릭하면 안으로 이동합니다.'
                self.switch_mode('preview')
                return
            self.file_badge.configure(text=(path.suffix[1:].upper() or 'FILE')[:5])
            self.preview_text = '실제 파일 형식과 안전한 파서를 확인하는 중…'
            self.switch_mode('preview')
            self.worker.start(action='inspect', path=str(path), memory_mb=self.profile.worker_mb)
            self.status.set('파일 형식 확인 및 미리보기 준비 중…')
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
            self.status.set('전체 경로를 복사했습니다.')

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
            self.pane_label.configure(text='원문 미리보기 · 최대 24,000자')
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
            self.status.set('선택 이후 파일이 변경되었습니다. 새로고침 후 다시 선택하세요.')
            return
        self.worker.stop()
        self.clear_summary_state()
        self.summary_result = None
        self.fallback_result = None
        self.summary_offset = 0
        try:
            self.summary_workspace = tempfile.TemporaryDirectory(prefix='summary-', dir=self.state_dir)
        except OSError as error:
            self.status.set('임시 작업 공간을 만들 수 없습니다. 저장 공간을 확인하세요: ' + str(error)[:150])
            return
        self.summary_state = Path(self.summary_workspace.name) / 'working.db'
        self.switch_mode('summary')
        self.section_bar.pack_forget()
        self.write_text('경량 요약을 준비하고 있습니다.\n\n원문 문장과 출처를 보존하며, 문서 전체의 각 섹션을 차례로 살펴봅니다.')
        self.pane_label.configure(text='경량 요약 · 처리 중')
        self.summary_button.configure(state='disabled')
        self.worker.start(action='summary', path=str(self.selected), workspace=str(self.summary_state), memory_mb=self.profile.worker_mb)
        self.status.set('문서 요약 중… 다른 파일을 선택하거나 Esc로 중단할 수 있습니다.')

    def display_summary(self, bullets, complete=False, detail=False):
        self.mode = 'summary'
        is_ai = complete and self.summary_result and self.summary_result.get('mode') == 'ai' and not detail
        structured = self.kind and self.kind.get('format') == 'xlsx'
        ai_label = 'AI 선택 · 구조 추출 / 완료' if structured else 'AI 선택 · 원문 그대로 / 완료'
        self.pane_label.configure(text='섹션별 원문 근거' if detail else ai_label if is_ai else 'Lightweight Summary · 완료' if complete else 'Quick Summary · 초벌 / 처리 중')
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        header = '%s\n%s\n%s\n수정: %s\n' % (self.selected.name, self.kind.get('label', 'Unknown'), self.selected, date_label(self.selected.stat().st_mtime) if self.selected.exists() else 'Unknown')
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
            self.text.insert('end', '한 줄 요약 · 추출 정보\n' if structured else '한 줄 요약 · 원문 발췌\n', 'heading')
            self.text.insert('end', (sentence or '문서의 핵심 내용을 확인하고 있습니다.') + '\n', 'summary_result')
            if selected:
                self.text.insert('end', '\n출처: %s\n' % selected['anchor'], 'anchor')
            if is_ai:
                self.text.insert('end', 'AI는 문장 선택만 수행합니다. 선택의 적절성은 원문과 함께 확인하세요.\n', 'muted')
            if structured:
                self.text.insert('end', '스프레드시트의 문장은 셀·범위·수식을 프로그램이 구조적으로 추출한 정보입니다.\n', 'muted')
        if complete:
            result = self.summary_result
            count = result.get('sections', 0) if result else len(bullets)
            self.text.insert('end', '\n아래 화살표에서 섹션별 원문 근거를 별도로 확인할 수 있습니다.', 'muted')
            if result and result.get('empty_pages'):
                self.text.insert('end', '\n텍스트 없는 페이지 %s개는 요약되지 않았습니다. OCR이 필요할 수 있습니다.' % result['empty_pages'], 'muted')
            self.section_label.configure(text='%s개 섹션 · 전체 근거' % count)
            self.section_bar.pack(side='bottom', fill='x')
        self.text.configure(state='disabled')

    def show_sections(self, delta):
        if not self.summary_result or not self.file_unchanged():
            self.status.set('원문이 변경되었거나 요약이 없습니다. 다시 선택하세요.')
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
            self.pane_label.configure(text='경량 요약 · 중단됨 / 미완성')
        if self.kind:
            self.summary_button.configure(state='normal' if self.kind.get('document') and self.kind.get('parser') else 'disabled')
        self.status.set('작업을 중단했습니다. 파일 탐색을 계속할 수 있습니다.')

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
                self.status.set(('폴더 읽기 실패: ' + error) if error else ('%s개 항목 · 준비됨' if done else '%s개 항목 발견 · 탐색 중…') % format(count, ','))
            for event in self.worker.drain():
                self.handle_event(event)
        except Exception as error:
            self.status.set('처리 오류: ' + str(error)[:150])
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
                self.count_label.configure(text='%s개 일치 · 본문 검색 중' % len(self.matches))
            return
        if name == 'search_done':
            self.searching = False
            self.count_label.configure(text='%s개 일치 · %s개 파일 검사' % (event['matches'], event['scanned']))
            self.status.set('검색 완료' + (' · 첫 160개 결과만 표시합니다. 검색어를 좁혀주세요.' if event['limited'] else ''))
            return
        if name == 'error':
            self.searching = False
            if self.worker.action == 'ai' and self.fallback_result:
                self.summary_result = self.fallback_result
                self.summary_button.configure(state='normal')
                self.display_summary(self.summary_result['bullets'], complete=True)
                self.status.set('경량 요약으로 전환: ' + event['message'])
                return
            if self.worker.action == 'summary':
                self.worker.stop()
                self.clear_summary_state()
            self.status.set(event['message'])
            if self.mode == 'summary':
                self.pane_label.configure(text='경량 요약 · 완료되지 않음')
            elif not self.kind:
                self.write_text(event['message'])
                self.identity_label.configure(text=getattr(self, 'basic_identity', '') + '\n유형   검증 실패 / 요약 불가')
            if self.kind:
                self.summary_button.configure(state='normal' if self.kind.get('document') and self.kind.get('parser') else 'disabled')
            return
        if not self.selected or not self.file_unchanged():
            self.summary_button.configure(state='disabled')
            self.status.set('처리 중 파일이 변경되었습니다. 결과를 표시하지 않습니다.')
            return
        if name == 'inspected':
            self.kind, self.info, self.preview_text = event['kind'], event['info'], event['preview']
            enabled = self.kind['document'] and self.kind['parser']
            self.summary_button.configure(state='normal' if enabled else 'disabled')
            self.file_subtitle.configure(text=self.kind['label'] + '\n' + str(self.selected))
            identity = self.basic_identity + '\n유형   ' + self.kind['label']
            identity += '\n제목   %s\n분량   %s\n언어   %s\n분류   %s' % tuple(self.info.get(k, 'Unknown') for k in ('title', 'count', 'language', 'category'))
            self.identity_label.configure(text=identity)
            if not self.preview_text:
                self.preview_text = self.kind['reason'] or '안전한 텍스트 미리보기를 제공할 수 없는 파일입니다.'
            if str(self.selected) in self.matches:
                match = self.matches[str(self.selected)]
                self.preview_text = '검색 일치 [%s]\n%s\n\n──────────\n\n%s' % (match['anchor'], match['snippet'], self.preview_text)
            self.switch_mode('preview')
            self.status.set('문서 검증 완료 · 요약 사용 가능' if enabled else self.kind['reason'] or '미리보기 준비됨')
        elif name == 'quick':
            if self.mode == 'summary':
                self.display_summary(event['bullets'])
        elif name == 'summary':
            self.info.update(event['info'])
            self.fallback_result = event
            if self.ai_config and profile().available >= 1280 * 1024**2:
                self.display_summary(event['bullets'], complete=False)
                self.pane_label.configure(text='Quick Summary · AI가 원문 선택 중')
                self.worker.start(action='ai', path=str(self.selected), workspace=str(self.summary_state), key=event['key'],
                                  content_hash=event['source']['content_hash'], memory_mb=768)
                return
            self.summary_result = event
            self.summary_button.configure(state='normal')
            self.display_summary(event['bullets'], complete=True)
            self.status.set('가용 메모리가 부족해 경량 요약을 제공합니다' if self.ai_config else '원문을 새로 읽어 요약했습니다 · 결과는 현재 선택 동안만 유지됩니다')
        elif name == 'ai_summary':
            self.summary_result = dict(self.fallback_result, **{k: v for k, v in event.items() if k != 'event'})
            self.summary_button.configure(state='normal')
            self.display_summary(self.summary_result['bullets'], complete=True)
            self.status.set(('AI 원문 선택 완료' if event['mode'] == 'ai' else '원문 문장으로 대체') + ' · %.1f초 · 모델 해제 · 캐시 없음' % event['total_ai_seconds'])
        elif name == 'sections':
            self.display_summary(event['bullets'], complete=True, detail=True)
            count = self.summary_result['sections']
            self.section_label.configure(text='%s–%s / %s개 섹션' % (event['offset'] + 1, min(count, event['offset'] + 24), count))

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
        try:
            (self.state_dir / 'settings.json').write_text(json.dumps({'folder': str(self.folder)}, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass
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
