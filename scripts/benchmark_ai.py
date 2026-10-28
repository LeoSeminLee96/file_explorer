"""Exercise the deployed CPU model through the same isolated workers as the UI."""
from __future__ import annotations

import json
import argparse
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from explorer.ai import load_config
from explorer.memory import constrain_process
from explorer.service import Worker


def run(worker, timeout=90, **request):
    worker.start(**request)
    deadline = time.monotonic() + timeout
    events = []
    while time.monotonic() < deadline:
        for event in worker.drain():
            events.append(event)
            if event['event'] in ('summary', 'ai_summary', 'error'):
                return event, events
        time.sleep(.025)
    worker.stop()
    raise TimeoutError('AI benchmark timed out')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-config')
    parser.add_argument('--output', default=str(ROOT / 'docs' / 'reports' / 'ai-benchmark.json'))
    args = parser.parse_args()
    config = load_config(args.model_config)
    if not config:
        raise SystemExit('Run scripts/setup_ai.py first')
    if not constrain_process(2048):
        raise RuntimeError('Unable to enforce 2GB process-tree budget')
    results = []
    for name in ('02_Product_Planning.md', '03_Quarterly_Operations.txt', '06_Product_Brief.pdf'):
        path = ROOT / 'sample_documents' / name
        with tempfile.TemporaryDirectory(prefix='ai-benchmark-', dir=ROOT / '.data') as temp:
            worker = Worker()
            try:
                workspace = str(Path(temp) / 'working.db')
                extraction, _ = run(worker, action='summary', path=str(path), workspace=workspace, memory_mb=256)
                if extraction['event'] == 'error':
                    raise RuntimeError(extraction['message'])
                started = time.perf_counter()
                ai, events = run(worker, action='ai', path=str(path), workspace=workspace, key=extraction['key'],
                    content_hash=extraction['source']['content_hash'], memory_mb=768, diagnostics=True,
                    model_config=args.model_config)
                record = dict(filename=name, elapsed_seconds=time.perf_counter() - started, result=ai)
                if ai['event'] == 'ai_summary':
                    from explorer.summary import source_sentences
                    item = ai['bullets'][0]
                    assert item['text'] in source_sentences(item['evidence'])
                    assert ai['verification'] == 'source_sentence'
                draft = Path(temp) / 'draft.txt'
                if draft.exists():
                    record['model_draft_for_validation'] = draft.read_text(encoding='utf-8')
                results.append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
            finally:
                worker.stop()
    target = Path(args.output)
    target.write_text(json.dumps(dict(model=config['model_id'], cpu_threads=2, context=2048,
        process_tree_limit_mb=2048, summary_cache=False, results=results), ensure_ascii=False, indent=2), encoding='utf-8')
    if any(row['result']['event'] == 'error' for row in results):
        raise SystemExit('At least one AI run failed; inspect docs/reports/ai-benchmark.json')


if __name__ == '__main__':
    main()
