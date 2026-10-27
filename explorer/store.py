from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from .parsers import PARSER_VERSION


def connect(path):
    db = sqlite3.connect(str(path), timeout=3)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA temp_store=FILE')
    return db


def init_state(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS sections(key TEXT, section TEXT, position INTEGER, anchor TEXT, excerpt TEXT, score REAL,
            PRIMARY KEY(key,section));
        CREATE INDEX IF NOT EXISTS sections_order ON sections(key, position);
    ''')


def stamp(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def identity(path):
    before = stamp(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    if before != stamp(path):
        raise ValueError('처리 중 파일이 변경되었습니다. 다시 선택하세요.')
    data = dict(stable_file_id='%s:%s' % before[:2], content_hash=digest.hexdigest(), file_size=before[2],
                modified_time=before[3], created_time=before[4], model_id='extractive', model_version='2',
                prompt_version='evidence-1', summary_mode='section-coverage', parser_version=PARSER_VERSION,
                canonical_path=os.path.normcase(str(path.resolve())))
    key = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return key, data, before
