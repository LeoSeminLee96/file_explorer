"""Integration test against real Tk widgets and isolated document workers."""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import Explorer, BASE


def wait(app, condition, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if condition():
            return
        time.sleep(.02)
    raise AssertionError('UI operation timed out: ' + app.status.get())


def main():
    with tempfile.TemporaryDirectory(prefix='explorer-ui-') as directory:
        app = Explorer(str(BASE / 'sample_documents'), directory, ai_enabled=False)
        try:
            wait(app, lambda: app.ready and not app.scan_running)
            assert len(app.tree.get_children()) >= 6
            app.tree.selection_set(str(BASE / 'sample_documents' / '02_Product_Planning.md'))
            wait(app, lambda: app.kind is not None)
            assert str(app.summary_button['state']) == 'normal'
            assert str(app.selected) in app.file_subtitle['text']
            assert 'Size' in app.identity_label['text']
            app.request_summary()
            wait(app, lambda: app.summary_result is not None)
            assert app.summary_result['sections'] >= 4
            assert 'Complete' in app.pane_label['text']
            old_workspace, old_key = app.summary_state.parent, app.summary_result['key']
            app.request_summary()
            wait(app, lambda: app.summary_result is not None)
            assert app.summary_result['key'] != old_key
            assert not old_workspace.exists()
            app.show_sections(0)
            wait(app, lambda: 'Source evidence' in app.pane_label['text'])
            app.tree.selection_set(str(BASE / 'sample_documents' / '05_Search_Example.py'))
            wait(app, lambda: app.kind is not None and app.kind['format'] == 'code')
            assert app.summary_workspace is None
            assert not list(Path(directory).glob('summary-*'))
            assert str(app.summary_button['state']) == 'disabled'
            assert 'find_document' in app.preview_text
            app.search_var.set('Product_Planning')
            app.search()
            assert len(app.tree.get_children()) == 1
            app.search_mode.set('File contents')
            app.search_var.set('MAX_VISIBLE_FILES')
            app.search()
            wait(app, lambda: not app.searching)
            assert len(app.matches) == 1, app.matches
            assert next(iter(app.matches.values()))['name'].endswith('.py')
            for _ in range(20):
                app.navigate(BASE / 'sample_documents', history=False)
            wait(app, lambda: app.ready and not app.scan_running)
            assert len(list(Path(directory).glob('listing-*.db'))) <= 4
            from scripts.benchmark import counters
            print(json.dumps({'ui_smoke': 'passed', 'checks': ['folder navigation', 'identity card', 'document summary',
                'section pagination', 'source summary disabled', 'name search', 'source content search',
                'rapid navigation', 'bounded snapshot cleanup', 'summary always recomputed', 'temporary summary deleted'],
                'process_metrics': counters()}, ensure_ascii=False))
        finally:
            app.close()


if __name__ == '__main__':
    main()
