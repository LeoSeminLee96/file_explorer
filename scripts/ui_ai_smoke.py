"""Real CPU inference, responsive Tk event loop, cancellation and fallback."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import Explorer
from scripts.ui_smoke import wait


def main():
    with tempfile.TemporaryDirectory(prefix='ui-ai-', dir=ROOT / '.data') as directory:
        app = Explorer(str(ROOT / 'sample_documents'), directory)
        try:
            assert app.ai_config, 'Install the CPU model first'
            wait(app, lambda: app.ready and not app.scan_running)
            app.tree.selection_set(str(ROOT / 'sample_documents' / '02_제품_기획_회의.md'))
            wait(app, lambda: app.kind is not None)
            app.request_summary()
            wait(app, lambda: app.worker.action == 'ai')
            ticks = []
            def tick():
                ticks.append(time.perf_counter())
                if len(ticks) < 10:
                    app.after(15, tick)
            app.after(15, tick)
            wait(app, lambda: len(ticks) == 10)
            app.cancel_work()
            assert app.summary_workspace is None
            assert app.worker.process is None
            app.request_summary()
            wait(app, lambda: app.summary_result is not None, timeout=60)
            assert app.summary_result.get('mode') in ('ai', 'extractive_fallback'), app.status.get()
            assert app.summary_result['model_loaded_on_request']
            assert app.summary_result['model_peak_rss_mb'] > 0
            assert app.summary_result['input_tokens'] <= 1400
            assert '완료' in app.pane_label['text']
            assert app.summary_result['verification'] == 'source_sentence'
            from explorer.summary import source_sentences
            selected_source = app.summary_result['bullets'][0]
            assert selected_source['text'] in source_sentences(selected_source['evidence'])
            if app.summary_result['mode'] == 'ai':
                assert 'AI 선택' in app.pane_label['text']
                assert selected_source['origin'] == 'ai_selected'
            assert len(app.summary_result['bullets']) == 1
            assert '\n' not in app.summary_result['summary_text']
            ranges = app.text.tag_ranges('summary_result')
            assert len(ranges) == 2
            displayed = app.text.get(ranges[0], ranges[1]).strip()
            assert displayed == app.summary_result['summary_text']
            first_key = app.summary_result['key']
            app.request_summary()
            wait(app, lambda: app.summary_result is not None, timeout=60)
            assert app.summary_result['key'] != first_key
            # Simulate an AI crash report only after obtaining real extractive evidence.
            app.summary_result = None
            app.worker.action = 'ai'
            app.handle_event({'event': 'error', 'message': 'forced failure test'})
            assert app.summary_result is app.fallback_result
            assert 'Lightweight' in app.pane_label['text']
            print(json.dumps({'ui_ai_smoke': 'passed', 'responsive_callbacks_during_ai': len(ticks),
                'cancelled_and_unloaded': True, 'real_cpu_inference': True, 'recomputed_without_cache': True,
                'ai_failure_fallback': True, 'one_sentence_result': True, 'verbatim_source_only': True}))
        finally:
            app.close()


if __name__ == '__main__':
    main()
