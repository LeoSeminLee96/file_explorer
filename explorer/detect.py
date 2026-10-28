from __future__ import annotations

import importlib.util
import math
import re
import struct
import zipfile
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

SOURCE = set('.rs .py .pyw .js .jsx .ts .tsx .java .cpp .cc .c .h .hpp .go .cs .php .rb .swift .kt .sh .bat .ps1 .sql .html .css .vue .svelte .ipynb'.split())
NEVER = SOURCE | set('.exe .dll .so .dylib .zip .7z .rar .tar .gz .db .sqlite .sqlite3 .gguf .onnx .iso .bin .png .jpg .jpeg .gif .svg .webp .mp4 .mp3 .wav .ttf .woff .sys .ini .cfg .conf .json .yaml .yml .toml .xml .log .tmp .csv .tsv .lock'.split())
TEXT_EXT = {'.txt', '.md', '.markdown', '.rst', ''}


@dataclass
class Kind:
    format: str
    label: str
    document: bool = False
    parser: bool = False
    reason: str = ''
    language: str = 'Unknown'

    @property
    def summarizable(self):
        return self.document and self.parser

    def dict(self):
        return asdict(self)


def decode(data: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-16' if data[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8', 'cp949'):
        try:
            return data.decode(encoding)
        except UnicodeError:
            pass
    return data.decode('utf-8', errors='replace')


def language(text: str) -> str:
    korean = len(re.findall('[가-힣]', text))
    english = len(re.findall('[A-Za-z]', text))
    return 'Korean / English' if korean > 10 and english > 30 else 'Korean' if korean > 5 else 'English' if english > 20 else 'Unknown'


def natural_text(text: str) -> bool:
    """Conservative, deterministic classifier. Never invokes a model."""
    text = text.strip()
    if len(text) < 30 or '\x00' in text or text.count('\ufffd') > len(text) * .01:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()][:500]
    if not lines:
        return False
    code = re.compile(r'(^\s*(def |class |import |from \w+ import|function |const |let |var |return |#include|package |using |public |if\s*\(|for\s*\(|SELECT |INSERT |export |//|/\*|```))|([{};]|=>|==|!=|\w+\([^)]*\)\s*[:;{])', re.I)
    machine = re.compile(r'^([\d\-/:T.\s]+\s*(INFO|WARN|ERROR|DEBUG)|[\w.\-]+\s*[=:]\s*\S+$|[0-9a-fA-F\s:]{24,}$|[\d,;\t.\s-]{20,}$)')
    if sum(bool(code.search(line) or machine.search(line)) for line in lines) / len(lines) > .17:
        return False
    if sum(len(line) > 1500 for line in lines) / len(lines) > .15:
        return False
    if sum(text.count(char) for char in '{}[];<>\\=') / len(text) > .035:
        return False
    letters = sum(char.isalpha() for char in text)
    words = re.findall(r'[A-Za-z가-힣]{2,}', text)
    identifiers = re.findall(r'\b\w+[_]\w+\b|\b[a-z]+[A-Z]\w*', text)
    counts = Counter(text)
    entropy = -sum((n / len(text)) * math.log2(n / len(text)) for n in counts.values())
    return letters / len(text) > .48 and len(words) >= 5 and len(identifiers) / max(1, len(words)) < .15 and entropy < 7.5


def checked_zip(path: Path) -> zipfile.ZipFile:
    # Check EOCD before ZipFile builds its in-memory central-directory list.
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 65557))
        tail = stream.read(65557)
    pos = tail.rfind(b'PK\x05\x06')
    if pos < 0 or len(tail) - pos < 22:
        raise ValueError('Invalid document container.')
    entries, directory_size = struct.unpack_from('<HI', tail, pos + 10)
    if entries == 65535 or entries > 20000 or directory_size > 8 * 1024**2:
        raise ValueError('Document container exceeds safety limits.')
    archive = zipfile.ZipFile(path)
    for entry in archive.infolist():
        if entry.flag_bits & 1 or entry.file_size > 256 * 1024**2:
            archive.close()
            raise ValueError('Document is encrypted or exceeds safety limits.')
    return archive


def detect(path: Path) -> Kind:
    ext = path.suffix.lower()
    with path.open('rb') as stream:
        head = stream.read(32768)
    if head.startswith((b'MZ', b'\x7fELF', b'\xcf\xfa\xed\xfe', b'SQLite format 3', b'GGUF')):
        return Kind('binary', 'Binary', reason='Executables and binary files cannot be summarized.')
    if ext in NEVER:
        is_text = ext in SOURCE or ext in {'.json', '.toml', '.yaml', '.yml', '.xml', '.log', '.ini', '.cfg', '.csv', '.tsv'}
        return Kind('code' if is_text else 'binary', 'Source / Data' if is_text else 'Binary', reason='Summaries are available only for documents.')
    if head.startswith(b'%PDF-'):
        available = importlib.util.find_spec('fitz') is not None
        if available:
            import fitz
            try:
                with fitz.open(path) as document:
                    valid = document.is_pdf and not document.needs_pass and document.page_count > 0
                if not valid:
                    return Kind('pdf', 'PDF Document', True, False, 'Check the document password and page validity.')
            except Exception:
                return Kind('binary', 'Invalid PDF', reason='PDF parser validation failed.')
        return Kind('pdf', 'PDF Document', True, available, '' if available else 'Install PDF support: pip install -r requirements.txt')
    if head.startswith(b'PK\x03\x04'):
        with checked_zip(path) as archive:
            names = set(archive.namelist())
            candidates = [('word/document.xml', 'docx', 'Word Document'),
                          ('ppt/presentation.xml', 'pptx', 'PowerPoint Presentation'),
                          ('xl/workbook.xml', 'xlsx', 'Excel Spreadsheet'),
                          ('Contents/content.hpf', 'hwpx', 'HWPX Document')]
            for marker, fmt, label in candidates:
                required = '[Content_Types].xml' in names if fmt != 'hwpx' else 'mimetype' in names
                if marker in names and required:
                    # Actual XML syntax is validated again by the streaming parser.
                    return Kind(fmt, label, True, True)
            if 'mimetype' in names and 'content.xml' in names:
                with archive.open('mimetype') as mime_stream:
                    mime = mime_stream.read(256).decode('ascii', errors='replace')
                for suffix, fmt, label in [('text', 'odt', 'OpenDocument Text'), ('presentation', 'odp', 'OpenDocument Presentation'), ('spreadsheet', 'ods', 'OpenDocument Spreadsheet')]:
                    if mime == 'application/vnd.oasis.opendocument.' + suffix:
                        return Kind(fmt, label, True, True)
        return Kind('binary', 'Archive', reason='No supported document structure found.')
    if head.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        return Kind('ole', 'Legacy Office / HWP', True, False, 'No safe parser available. Convert to DOCX, PPTX, XLSX, or HWPX.')
    if head.startswith(b'{\\rtf'):
        return Kind('rtf', 'RTF Document', True, False, 'No safe RTF parser available. Convert to TXT or DOCX.')
    text = decode(head)
    # A renamed binary/container or a mismatched document extension is never plaintext.
    if ext not in TEXT_EXT or b'\x00' in head and not head.startswith((b'\xff\xfe', b'\xfe\xff')):
        return Kind('binary', 'Unverified File', reason='Unable to verify the actual file format.')
    prose = natural_text(text)
    return Kind('markdown' if ext in {'.md', '.markdown'} else 'text', 'Markdown Document' if ext in {'.md', '.markdown'} else 'Text Document', prose, prose,
                '' if prose else 'Content appears to be code, configuration, logs, or unverified prose.', language(text))
