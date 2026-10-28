from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from explorer.detect import detect, natural_text
from explorer.files import scan, page, PAGE_SIZE
from explorer.parsers import segments, metadata
from explorer.service import Worker
from explorer.store import connect, identity
from explorer.summary import summarize, verify_claim, section_page

PROSE = 'The project reviewed 1,250 documents in October 2026. The key result was an 18% increase in accuracy. '


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'working.db'
        self.db = connect(self.workspace)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return path

    def archive(self, name, entries):
        path = self.root / name
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for key, value in entries.items():
                archive.writestr(key, value)
        return path

    def test_spoofed_pdf_executable_and_source_denied(self):
        path = self.root / 'report.pdf'
        path.write_bytes(b'MZ' + b'\0' * 200)
        self.assertFalse(detect(path).summarizable)
        for suffix in ('.py', '.js', '.json', '.gguf', '.exe', '.log'):
            self.assertFalse(detect(self.write('prose' + suffix, PROSE * 100)).summarizable)

    def test_text_heuristic_rejects_disguised_code_logs_and_config(self):
        for text in ['def example(value):\n    return value + 3\n' * 50,
                     '2026-10-27 12:00:00 INFO Generated request 1234\n' * 50,
                     'model_path=/data/model.gguf\nport=8080\nenabled=true\n' * 50,
                     'const value = () => { return 32; };\n' * 50,
                     '48 65 6c 6c 6f 20 77 6f 72 6c 64\n' * 50]:
            self.assertFalse(natural_text(text), text[:50])
            self.assertFalse(detect(self.write('disguised.txt', text)).summarizable)
        self.assertTrue(detect(self.write('notes.md', '# Meeting notes\n\n' + PROSE)).summarizable)

    def test_extensionless_pdf_validated_and_scanned_pdf_does_not_invent(self):
        import fitz
        path = self.root / 'extensionless'
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()
        self.assertEqual(detect(path).format, 'pdf')
        with self.assertRaisesRegex(ValueError, 'text'):
            summarize(path, detect(path), self.db, metadata(path, detect(path)))

    def test_docx_structure_headings_tables_and_extensionless(self):
        path = self.archive('no-extension', {'[Content_Types].xml': '<Types/>', 'word/document.xml':
            '<w:document xmlns:w="urn:w"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Results</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>' + PROSE + '</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'})
        kind = detect(path)
        self.assertEqual(kind.format, 'docx')
        items = list(segments(path, kind))
        self.assertTrue(items[0].heading)
        self.assertEqual(items[1].section, 'Results')
        self.assertIn('1,250', items[1].text)

    def test_malformed_container_fails_parser(self):
        path = self.archive('bad.docx', {'[Content_Types].xml': '<Types/>', 'word/document.xml': '<broken>'})
        with self.assertRaises(Exception):
            list(segments(path, detect(path)))
        arbitrary = self.archive('renamed.docx', {'data.txt': PROSE})
        self.assertFalse(detect(arbitrary).summarizable)

    def test_xlsx_shared_strings_and_real_sheet_names(self):
        path = self.archive('budget.xlsx', {
            '[Content_Types].xml': '<Types/>',
            'xl/workbook.xml': '<workbook xmlns:r="urn:r"><sheets><sheet name="Revenue" r:id="rId7"/></sheets></workbook>',
            'xl/_rels/workbook.xml.rels': '<Relationships><Relationship Id="rId7" Target="worksheets/sheet3.xml"/></Relationships>',
            'xl/sharedStrings.xml': '<sst><si><t>Sales</t></si></sst>',
            'xl/worksheets/sheet3.xml': '<worksheet><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1"><f>2+3</f><v>5</v></c></row></sheetData></worksheet>'})
        items = list(segments(path, detect(path)))
        self.assertEqual(items[0].anchor, 'Revenue!A1:B1')
        self.assertIn('Sales', items[0].text)
        self.assertIn('formulas: 1', items[0].text)

    def test_pptx_notes_use_relationship_not_slide_number(self):
        path = self.archive('slides.pptx', {'[Content_Types].xml': '<Types/>', 'ppt/presentation.xml': '<presentation/>',
            'ppt/slides/slide1.xml': '<slide><p><t>First slide</t></p></slide>',
            'ppt/slides/_rels/slide1.xml.rels': '<Relationships><Relationship Type="http://x/notesSlide" Target="../notesSlides/notesSlide9.xml"/></Relationships>',
            'ppt/notesSlides/notesSlide9.xml': '<notes><p><t>Important speaker evidence.</t></p></notes>'})
        items = list(segments(path, detect(path)))
        self.assertEqual(items[-1].anchor, 'Speaker notes 1')
        self.assertIn('speaker evidence', items[-1].text)

    def test_every_summary_rereads_source_without_reusing_results(self):
        first = self.write('notes.md', '# Introduction\n\n' + PROSE + '\n\n# Conclusion\n\n' + PROSE.replace('18%', '25%'))
        kind = detect(first)
        one = summarize(first, kind, self.db, metadata(first, kind))
        notices = []
        two = summarize(first, kind, self.db, metadata(first, kind), notices.append)
        self.assertNotIn('cached', one)
        self.assertNotIn('cached', two)
        self.assertNotEqual(one['key'], two['key'])
        self.assertTrue(any(n['event'] == 'quick' for n in notices))
        self.assertEqual(self.db.execute('SELECT count(DISTINCT key) FROM sections').fetchone()[0], 1)
        first.write_text(first.read_text() + '\nNew finding: 42 documents were verified.', encoding='utf-8')
        three = summarize(first, kind, self.db, metadata(first, kind))
        self.assertNotEqual(one['key'], three['key'])
        other = self.root / 'other'
        other.mkdir()
        copy = other / first.name
        copy.write_bytes(first.read_bytes())
        self.assertNotEqual(identity(first)[0], identity(copy)[0])

    def test_modified_during_summary_result_discarded(self):
        path = self.write('notes.md', '# One\n\n' + PROSE + '\n\n# Two\n\n' + PROSE)
        def mutate(event):
            if event['event'] == 'quick':
                path.write_text(path.read_text() + '\nChanged.', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed'):
            summarize(path, detect(path), self.db, {}, mutate)

    def test_all_sections_preserved_and_late_evidence_in_overview(self):
        path = self.write('long.md', '\n\n'.join('# Section %d\n\n%s Final metric %d.' % (i, PROSE, i) for i in range(120)))
        result = summarize(path, detect(path), self.db, {})
        self.assertEqual(result['sections'], 120)
        self.assertEqual(result['bullets'][-1]['section'], 'Section 119')
        self.assertEqual(len(section_page(self.db, result['key'], 96)), 24)
        self.assertTrue(verify_claim('18%', PROSE))
        self.assertFalse(verify_claim('19%', PROSE))

    def test_major_decision_between_coverage_positions_is_selected(self):
        sections = []
        for i in range(20):
            heading = '주요 결정' if i == 13 else 'Section %d' % i
            sections.append('# %s\n\n%s' % (heading, PROSE))
        path = self.write('coverage.md', '\n\n'.join(sections))
        result = summarize(path, detect(path), self.db, {})
        self.assertIn('주요 결정', [item['section'] for item in result['bullets']])
        self.assertEqual(result['sections'], 20)
        self.assertEqual(result['bullets'][-1]['section'], 'Section 19')

    def test_metadata_search_paged_and_literal_wildcards(self):
        folder = self.root / 'corpus'
        folder.mkdir()
        for i in range(350):
            (folder / ('file-%03d.txt' % i)).write_text(PROSE)
        (folder / '100%_done.txt').write_text(PROSE)
        filename = self.root / 'files.db'
        self.assertEqual(scan(folder, filename), 351)
        rows, total = page(filename)
        self.assertEqual(total, 351)
        self.assertEqual(len(rows), PAGE_SIZE)
        self.assertEqual(page(filename, '100%_')[1], 1)
        self.assertEqual(len(page(filename, offset=320)[0]), 31)

    def test_corrupt_document_worker_does_not_kill_host(self):
        path = self.root / 'bad.pdf'
        path.write_bytes(b'%PDF-1.7\nnot a valid PDF')
        worker = Worker()
        worker.start(action='inspect', path=str(path), memory_mb=128)
        events = []
        deadline = time.monotonic() + 15
        try:
            while time.monotonic() < deadline:
                events.extend(worker.drain())
                if worker.reported_exit:
                    break
                time.sleep(.03)
            self.assertTrue(events)
            self.assertTrue(any(e['event'] in ('error', 'inspected') for e in events))
        finally:
            worker.stop()

    def test_worker_terminated_then_reused(self):
        path = self.write('notes.md', '# Notes\n\n' + PROSE)
        worker = Worker()
        try:
            for _ in range(8):
                worker.start(action='inspect', path=str(path), memory_mb=128)
                worker.stop()
            worker.start(action='inspect', path=str(path), memory_mb=128)
            deadline, events = time.monotonic() + 15, []
            while time.monotonic() < deadline:
                events.extend(worker.drain())
                if any(e['event'] == 'inspected' for e in events):
                    break
                time.sleep(.03)
            self.assertTrue(any(e['event'] == 'inspected' for e in events))
        finally:
            worker.stop()


if __name__ == '__main__':
    unittest.main()
