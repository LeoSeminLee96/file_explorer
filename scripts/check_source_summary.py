"""Verify actual CPU-selected results against the original parsed sources."""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from explorer.ai import load_config
from explorer.detect import detect
from explorer.memory import constrain_process
from explorer.parsers import segments
from explorer.service import Worker
from explorer.summary import normalize_source, source_sentences
from scripts.benchmark_ai import run
from scripts.compare_quality import CASES


def main():
    assert load_config(), 'Install the small CPU model first'
    assert constrain_process(2048), 'OS memory ceiling was not applied'
    results = []
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix='source-check-', dir=ROOT / '.data') as temp:
            workdir = Path(temp)
            if 'sample' in case:
                document = ROOT / 'sample_documents' / case['sample']
            else:
                document = workdir / (case['title'] + '.md')
                document.write_text(case['text'], encoding='utf-8')
            worker = Worker()
            try:
                workspace = str(workdir / 'working.db')
                extraction, _ = run(worker, action='summary', path=str(document), workspace=workspace, memory_mb=256)
                assert extraction['event'] == 'summary', extraction
                started = time.perf_counter()
                result, _ = run(worker, action='ai', path=str(document), workspace=workspace,
                    key=extraction['key'], content_hash=extraction['source']['content_hash'], memory_mb=768, diagnostics=True)
                assert result['event'] == 'ai_summary', result
                assert len(result['bullets']) == 1
                sentence = result['summary_text']
                chosen = result['bullets'][0]
                assert chosen['verification'] == 'source_sentence'
                assert sentence in source_sentences(chosen['evidence'])
                assert any(item['text'] == sentence and item['anchor'] == chosen['anchor'] for item in result['candidate_sentences'])
                found_in_original = any(segment.anchor == chosen['anchor'] and sentence in source_sentences(segment.text)
                                        for segment in segments(document, detect(document)))
                assert found_in_original, 'The selected text/anchor did not match the original parser output'
                record = dict(case=case['id'], mode=result['mode'], method=result['summary_method'],
                    sentence=sentence, anchor=chosen['anchor'], exact_source_match=found_in_original,
                    model_response=result['draft_for_validation'], candidates=result['candidate_count'],
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    model_peak_rss_mb=round(result['model_peak_rss_mb'], 2), generated_tokens=result['generated_tokens'])
                results.append(record)
                print(json.dumps(record, ensure_ascii=True), flush=True)
            finally:
                worker.stop()
    report = dict(method='AI selects an ID; application copies a source sentence without rewriting',
        scope='Exact source preservation and anchor checks, not a proof of document truth or representative selection',
        model=load_config()['model_id'], process_tree_limit_mb=2048, result_cache=False,
        all_exact_source_matches=all(item['exact_source_match'] for item in results), results=results)
    (ROOT / 'docs' / 'source-selection-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
