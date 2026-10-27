from __future__ import annotations

import codecs
import posixpath
import re
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .detect import Kind, checked_zip, decode

PARSER_VERSION = 'stream-3'
BLOCK = 16384


@dataclass
class Segment:
    section: str
    anchor: str
    text: str
    heading: bool = False


def local(tag):
    return tag.rsplit('}', 1)[-1]


def xml_elements(archive, name, tags):
    """Discard processed subtrees, including from their parents."""
    with archive.open(name) as stream:
        stack = []
        for event, element in ET.iterparse(stream, events=('start', 'end')):
            if event == 'start':
                stack.append(element)
                continue
            tag = local(element.tag)
            if tag in tags:
                yield tag, element
                if len(stack) > 1:
                    stack[-2].remove(element)
                element.clear()
            elif tag in {'tr', 'tbl', 'table-row', 'table', 'row'} and not any(local(parent.tag) in tags for parent in stack[:-1]):
                if len(stack) > 1:
                    stack[-2].remove(element)
                element.clear()
            stack.pop()


def xml_text(element):
    # itertext is capped as individual text nodes can be untrusted.
    parts, length = [], 0
    for text in element.itertext():
        parts.append(text[:BLOCK - length])
        length += len(parts[-1])
        if length >= BLOCK:
            break
    return ' '.join(parts).strip()


def stream_text(path):
    with path.open('rb') as stream:
        first = stream.read(32768)
        encoding = 'utf-16' if first[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8-sig'
        try:
            first.decode(encoding)
        except UnicodeError:
            encoding = 'cp949'
        stream.seek(0)
        reader = codecs.getreader(encoding)(stream, errors='replace')
        line_number, paragraph, size = 0, [], 0
        section = '본문'
        while True:
            # readline(size) prevents a single giant line from defeating the bound.
            line = reader.readline(BLOCK)
            if not line:
                break
            line_number += 1
            clean = line.strip()
            heading = bool(re.match(r'^#{1,6}\s+\S', clean))
            if not clean or heading or size + len(clean) > BLOCK:
                if paragraph:
                    yield Segment(section if section != '본문' else '문단 %d' % start, '줄 %d' % start, ' '.join(paragraph))
                paragraph, size = [], 0
            if heading:
                section = clean.lstrip('# ').strip()[:160]
                yield Segment(section, '줄 %d' % line_number, section, True)
            elif clean:
                if not paragraph:
                    start = line_number
                paragraph.append(clean)
                size += len(clean)
        if paragraph:
            yield Segment(section if section != '본문' else '문단 %d' % start, '줄 %d' % start, ' '.join(paragraph))


def segments(path: Path, kind: Kind):
    fmt = kind.format
    if fmt in ('text', 'markdown', 'code'):
        yield from stream_text(path)
        return
    if fmt == 'pdf':
        import fitz
        # Disable MuPDF's optional store: page resources are released between pages.
        fitz.TOOLS.store_shrink(100)
        with fitz.open(path) as document:
            if document.needs_pass:
                raise ValueError('암호화된 PDF입니다.')
            repeated = Counter()
            def edge_key(block, height):
                if block[1] < height * .07 or block[3] > height * .90:
                    return re.sub(r'[\d\s]+', ' ', block[4]).strip()
                return ''
            for page_index in range(min(3, document.page_count)):
                page = document[page_index]
                keys = {edge_key(block, page.rect.height) for block in page.get_text('blocks') if len(block) >= 7 and block[6] == 0}
                repeated.update(key for key in keys if key)
            for number, page in enumerate(document):
                texts = []
                for block in page.get_text('blocks', sort=True):
                    if len(block) < 7 or block[6] != 0:
                        continue
                    key = edge_key(block, page.rect.height)
                    if key and repeated.get(key, 0) >= 2:
                        continue
                    if not key and block[4].strip().isdigit() and block[3] > page.rect.height * .90:
                        continue
                    texts.append(block[4])
                text = '\n'.join(texts)
                for index in range(0, len(text), BLOCK):
                    yield Segment('페이지 %d' % (number + 1), 'p. %d' % (number + 1), text[index:index + BLOCK])
                # Empty scanned pages are represented explicitly, never invented.
                if not text.strip():
                    yield Segment('페이지 %d' % (number + 1), 'p. %d' % (number + 1), '')
                if number % 20 == 0:
                    fitz.TOOLS.store_shrink(100)
        return
    with checked_zip(path) as archive:
        if fmt == 'docx':
            section, number = '본문', 0
            for _, element in xml_elements(archive, 'word/document.xml', {'p'}):
                number += 1
                text = ' '.join((e.text or '') for e in element.iter() if local(e.tag) == 't')[:BLOCK]
                is_heading = any(local(e.tag) == 'pStyle' and any(str(v).lower().startswith(('heading', 'title')) for v in e.attrib.values()) for e in element.iter())
                if is_heading:
                    section = text[:160] or section
                if text.strip():
                    yield Segment(section, '문단 %d' % number, text, is_heading)
            return
        if fmt == 'pptx':
            names = sorted((n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)), key=lambda n: int(re.search(r'slide(\d+)', n).group(1)))
            for name in names:
                number = re.search(r'slide(\d+)', name).group(1)
                for _, element in xml_elements(archive, name, {'p'}):
                    text = xml_text(element)
                    if text:
                        yield Segment('슬라이드 ' + number, 'slide ' + number, text)
                relation_name = 'ppt/slides/_rels/slide%s.xml.rels' % number
                if relation_name in archive.namelist():
                    for _, relation in xml_elements(archive, relation_name, {'Relationship'}):
                        if relation.attrib.get('TargetMode') == 'External':
                            continue
                        relation_type = relation.attrib.get('Type', '').rsplit('/', 1)[-1]
                        if relation_type not in ('notesSlide', 'chart'):
                            continue
                        target = relation.attrib.get('Target', '')
                        extra = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('ppt/slides', target))
                        if extra not in archive.namelist():
                            continue
                        anchor = '발표자 노트 ' if relation_type == 'notesSlide' else '차트 '
                        for _, element in xml_elements(archive, extra, {'p', 'v'}):
                            text = xml_text(element)
                            if text:
                                yield Segment('슬라이드 ' + number, anchor + number, text)
            return
        if fmt == 'xlsx':
            yield from spreadsheet(archive)
            return
        if fmt == 'hwpx':
            for name in sorted(n for n in archive.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n)):
                number = 0
                for _, element in xml_elements(archive, name, {'p'}):
                    number += 1
                    text = xml_text(element)
                    if text:
                        yield Segment(name, '%s · 문단 %d' % (name, number), text)
            return
        section, number = '본문', 0
        # ODF maintains text headings, slide and table names.
        with archive.open('content.xml') as stream:
            stack = []
            for event, element in ET.iterparse(stream, events=('start', 'end')):
                tag = local(element.tag)
                if event == 'start':
                    stack.append(element)
                    if tag in ('page', 'table'):
                        section = next((v for k, v in element.attrib.items() if local(k) == 'name'), section)[:160]
                    continue
                if tag in ('p', 'h'):
                    number += 1
                    text = xml_text(element)
                    if tag == 'h':
                        section = text[:160]
                    if text:
                        yield Segment(section, '%s · 문단 %d' % (section, number), text, tag == 'h')
                    if len(stack) > 1:
                        stack[-2].remove(element)
                    element.clear()
                elif tag in ('table-row', 'page', 'table'):
                    if len(stack) > 1:
                        stack[-2].remove(element)
                    element.clear()
                stack.pop()


def spreadsheet(archive):
    """Disk-backed shared strings; numeric aggregates rather than cell dumps."""
    with tempfile.TemporaryDirectory(prefix='folio-sheet-') as temp:
        db = sqlite3.connect(str(Path(temp) / 'strings.db'))
        try:
            db.execute('PRAGMA cache_size=-1024')
            db.execute('CREATE TABLE strings(id INTEGER PRIMARY KEY, text TEXT)')
            if 'xl/sharedStrings.xml' in archive.namelist():
                for number, (_, element) in enumerate(xml_elements(archive, 'xl/sharedStrings.xml', {'si'})):
                    db.execute('INSERT INTO strings VALUES (?,?)', (number, xml_text(element)[:2048]))
                db.commit()
            relations = {}
            for _, element in xml_elements(archive, 'xl/_rels/workbook.xml.rels', {'Relationship'}):
                target = element.attrib.get('Target', '')
                if element.attrib.get('TargetMode') != 'External':
                    relations[element.attrib.get('Id', '')] = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            sheets = []
            for _, element in xml_elements(archive, 'xl/workbook.xml', {'sheet'}):
                relation = next((v for k, v in element.attrib.items() if local(k) == 'id'), '')
                sheets.append((element.attrib.get('name', 'Sheet'), relations.get(relation)))
            for sheet, name in sheets:
                if not name or name not in archive.namelist():
                    continue
                cells, formulas, numeric, total, minimum, maximum = 0, 0, 0, 0.0, None, None
                headers, first, last = [], '', ''
                for _, row in xml_elements(archive, name, {'row'}):
                    for cell in row:
                        if local(cell.tag) != 'c':
                            continue
                        cells += 1
                        ref = cell.attrib.get('r', '?')
                        first, last = first or ref, ref
                        value = next((e.text or '' for e in cell if local(e.tag) == 'v'), '')
                        if any(local(e.tag) == 'f' for e in cell):
                            formulas += 1
                        if cell.attrib.get('t') == 's' and value.isdigit():
                            result = db.execute('SELECT text FROM strings WHERE id=?', (int(value),)).fetchone()
                            value = result[0] if result else ''
                        elif cell.attrib.get('t') == 'inlineStr':
                            value = xml_text(cell)
                        else:
                            try:
                                amount = float(value)
                                numeric += 1
                                total += amount
                                minimum = amount if minimum is None else min(minimum, amount)
                                maximum = amount if maximum is None else max(maximum, amount)
                            except ValueError:
                                pass
                        if len(headers) < 16 and value and not re.fullmatch(r'[-+\d.Ee]+', value):
                            headers.append('%s: %s' % (ref, value[:100]))
                text = ('시트: %s. 사용 범위: %s:%s. 셀 %d개, 수식 %d개, 숫자 셀 %d개. '
                        '텍스트/헤더: %s.' % (sheet, first, last, cells, formulas, numeric, '; '.join(headers)))
                if numeric:
                    text += ' 숫자 셀 통계(서로 다른 단위가 섞일 수 있음): 최소 %s, 최대 %s, 합계 %s.' % (minimum, maximum, total)
                yield Segment(sheet, '%s!%s:%s' % (sheet, first, last), text)
        finally:
            db.close()


def metadata(path: Path, kind: Kind):
    result = {'title': path.stem, 'count': 'Unknown', 'category': 'Unknown', 'language': kind.language}
    if kind.format == 'pdf' and kind.parser:
        import fitz
        with fitz.open(path) as document:
            result.update(title=document.metadata.get('title') or path.stem, count='%d pages' % document.page_count)
    elif kind.format in ('docx', 'pptx', 'xlsx', 'hwpx', 'odt', 'odp', 'ods'):
        with checked_zip(path) as archive:
            names = archive.namelist()
            if 'docProps/core.xml' in names:
                for tag, element in xml_elements(archive, 'docProps/core.xml', {'title', 'language', 'category'}):
                    if element.text:
                        result[tag] = element.text[:256]
            if kind.format == 'pptx':
                result.update(count='%d slides' % sum(bool(re.fullmatch(r'ppt/slides/slide\d+\.xml', n)) for n in names), category='Presentation')
            elif kind.format == 'xlsx':
                count = sum(1 for _ in xml_elements(archive, 'xl/workbook.xml', {'sheet'}))
                result.update(count='%d sheets' % count, category='Spreadsheet')
            elif 'docProps/app.xml' in names:
                for _, element in xml_elements(archive, 'docProps/app.xml', {'Pages'}):
                    if element.text and element.text != '0':
                        result['count'] = element.text + ' pages (metadata)'
    return result
