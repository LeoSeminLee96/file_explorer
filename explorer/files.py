from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from .store import connect

SKIP = {'.git', '.venv', 'node_modules', '__pycache__', '$RECYCLE.BIN', 'System Volume Information', '.data'}
PAGE_SIZE = 160


def record(entry):
    try:
        stat = entry.stat(follow_symlinks=False)
        return (entry.path, entry.name, int(entry.is_dir(follow_symlinks=False)), stat.st_size, stat.st_mtime, Path(entry.name).suffix.lower())
    except OSError:
        return None


def file_db(filename):
    db = connect(filename)
    db.executescript('''CREATE TABLE IF NOT EXISTS files(
        path TEXT PRIMARY KEY, name TEXT, directory INTEGER, size INTEGER, modified REAL, extension TEXT);
        CREATE TABLE IF NOT EXISTS pending(path TEXT PRIMARY KEY);
        CREATE INDEX IF NOT EXISTS files_sort ON files(directory DESC, name COLLATE NOCASE);
    ''')
    return db


def scan(root, filename, recursive=False, cancelled=lambda: False, progress=lambda count: None):
    """All pending directories and file metadata live on disk, not in a Python list."""
    db = file_db(filename)
    try:
        db.execute('DELETE FROM files')
        db.execute('DELETE FROM pending')
        db.execute('INSERT INTO pending VALUES (?)', (str(root),))
        db.commit()
        count, last = 0, time.monotonic()
        while not cancelled():
            row = db.execute('SELECT path FROM pending LIMIT 1').fetchone()
            if not row:
                break
            db.execute('DELETE FROM pending WHERE path=?', row)
            try:
                with os.scandir(row[0]) as entries:
                    for entry in entries:
                        if cancelled():
                            break
                        item = record(entry)
                        if not item:
                            continue
                        db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?,?,?)', item)
                        count += 1
                        if recursive and item[2] and entry.name not in SKIP and not entry.is_symlink() and not os.path.islink(entry.path):
                            # Windows junctions are reparse points; never traverse them.
                            stat = entry.stat(follow_symlinks=False)
                            if not getattr(stat, 'st_file_attributes', 0) & 0x400:
                                db.execute('INSERT OR IGNORE INTO pending VALUES(?)', (entry.path,))
                        if count % 256 == 0:
                            db.commit()
                        if time.monotonic() - last > .3:
                            db.commit()
                            progress(count)
                            last = time.monotonic()
            except (PermissionError, FileNotFoundError, OSError):
                pass
            db.commit()
            if not recursive:
                break
        progress(count)
        return count
    finally:
        db.close()


def page(filename, query='', offset=0, documents=False, sort='name', descending=False):
    db = file_db(filename)
    try:
        clauses, args = [], []
        if query:
            pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            clauses.append("(name LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')")
            args.extend([pattern, pattern])
        if documents:
            clauses.append("(directory=1 OR extension IN ('.pdf','.doc','.docx','.odt','.rtf','.hwp','.hwpx','.ppt','.pptx','.odp','.xls','.xlsx','.ods','.txt','.md','.markdown'))")
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        count = db.execute('SELECT count(*) FROM files' + where, args).fetchone()[0]
        order = {'name': 'name COLLATE NOCASE', 'size': 'size', 'modified': 'modified', 'extension': 'extension'}.get(sort, 'name COLLATE NOCASE')
        rows = db.execute('SELECT * FROM files' + where + ' ORDER BY directory DESC,' + order + (' DESC' if descending else ' ASC') + ' LIMIT ? OFFSET ?', args + [PAGE_SIZE, offset]).fetchall()
        return rows, count
    finally:
        db.close()
