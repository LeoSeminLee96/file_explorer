"""Check actual Tk geometry across DPI/zoom combinations without loading AI."""
import json
import sys
import tempfile
from pathlib import Path
from tkinter import font as tkfont, ttk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Explorer
from scripts.ui_smoke import wait


def fully_visible(widget):
    assert widget.winfo_ismapped(), (widget, 'not mapped')
    x, y, width, height = 0, 0, widget.winfo_width(), widget.winfo_height()
    child = widget
    while child.master:
        x, y = x + child.winfo_x(), y + child.winfo_y()
        parent = child.master
        assert x >= 0 and y >= 0 and x + width <= parent.winfo_width() + 1 and y + height <= parent.winfo_height() + 1, (
            str(widget), str(parent), (x, y, width, height), (parent.winfo_width(), parent.winfo_height()))
        child = parent


def main():
    with tempfile.TemporaryDirectory(prefix='ui-scale-') as directory:
        app = Explorer(str(ROOT / 'sample_documents'), directory, ai_enabled=False)
        try:
            wait(app, lambda: app.ready and not app.scan_running)
            cases = []
            for dpi in (1.0, 1.25, 1.5, 2.0):
                app.ui.dpi_scale = dpi
                for zoom in ('100%', '125%', '150%', '100%'):
                    app.scale_var.set(zoom)
                    app.change_scale()
                    app.update()
                    for widget in (app.scale_selector, app.preview_button, app.summary_button, app.cancel_button, app.text):
                        fully_visible(widget)
                    if app.sidebar.winfo_ismapped():
                        fully_visible(app.brand_title)
                        assert app.brand_title.winfo_width() >= app.brand_title.winfo_reqwidth()
                    rowheight = int(ttk.Style(app).lookup('Treeview', 'rowheight'))
                    assert rowheight > app.ui.font(10).metrics('linespace')
                    assert app.ui.font(8).cget('size') == -app.ui.px(12)
                    cases.append({'dpi': dpi, 'zoom': zoom, 'sidebar_visible': bool(app.sidebar.winfo_ismapped())})
            # A repeat zoom cycle must not accumulate rounded dimensions.
            work_area = app.ui.work_area
            app.ui.work_area = lambda: (1320, 1000)
            app.ui.dpi_scale = 1.5
            app.scale_var.set('125%')
            app.change_scale()
            app.update()
            assert not app.sidebar.winfo_ismapped()
            for widget in (app.scale_selector, app.preview_button, app.summary_button, app.cancel_button, app.text):
                fully_visible(widget)
            app.ui.work_area = work_area
            app.ui.dpi_scale = 1.0
            app.scale_var.set('100%')
            app.change_scale()
            app.geometry('1120x740')
            app.update()
            def check_sidebar(widget):
                fully_visible(widget)
                for child in widget.winfo_children():
                    check_sidebar(child)
            check_sidebar(app.sidebar)
            for widget in (app.scale_selector, app.preview_button, app.summary_button, app.cancel_button, app.text):
                fully_visible(widget)
            baseline = (app.sidebar.cget('width'), app.ui.font(10).actual('size'), app.preview_button.cget('padx'))
            for _ in range(3):
                app.change_scale(1)
                app.change_scale(-1)
            app.update()
            assert baseline == (app.sidebar.cget('width'), app.ui.font(10).actual('size'), app.preview_button.cget('padx'))
            app.tree.selection_set(str(ROOT / 'sample_documents/02_Product_Planning.md'))
            wait(app, lambda: app.kind is not None)
            app.request_summary()
            wait(app, lambda: app.summary_result is not None)
            key, workspace = app.summary_result['key'], app.summary_state
            contents = app.text.get('1.0', 'end')
            app.scale_var.set('125%')
            app.change_scale()
            app.update()
            assert app.summary_result['key'] == key and app.summary_state == workspace
            assert app.text.get('1.0', 'end') == contents
            assert json.loads((Path(directory) / 'settings.json').read_text(encoding='utf-8'))['ui_scale'] == '125%'
        finally:
            app.close()
        app = Explorer(state_dir=directory, ai_enabled=False)
        try:
            assert app.scale_var.get() == '125%'
            assert app.folder == ROOT / 'sample_documents'
        finally:
            app.close()
        print(json.dumps({'ui_scale_smoke': 'passed', 'geometry_cases': cases,
            'compact_layout': True, 'minimum_window_sidebar': True,
            'no_rounding_drift': True, 'summary_preserved': True, 'settings_restored': True}))


if __name__ == '__main__':
    if '--review' in sys.argv:
        with tempfile.TemporaryDirectory(prefix='ui-review-') as directory:
            app = Explorer(str(ROOT / 'sample_documents'), directory, ai_enabled=False)
            app.title('Document Explorer - UI review')
            app.after(120000, app.close)
            app.mainloop()
    else:
        main()
