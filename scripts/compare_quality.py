"""Compare two small CPU models using the real document pipeline.

Topic keyword checks are diagnostics, not a semantic accuracy score. Raw drafts
and final outputs are retained only for these synthetic benchmark fixtures.
"""
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_ai import run
from explorer.memory import constrain_process
from explorer.service import Worker

# Multilingual source text belongs to regression data, not script messages.
CASES = json.loads((ROOT / 'tests' / 'fixtures' / 'summary_cases.json').read_text(encoding='utf-8'))


def main():
    assert constrain_process(2048), 'A real OS memory ceiling is required'
    results = []
    for config in ('.data/model.json', '.data/model-candidate.json'):
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix='quality-', dir=ROOT / '.data') as temp:
                workdir = Path(temp)
                if 'fixture' in case:
                    document = ROOT / 'tests' / 'fixtures' / 'korean' / case['fixture']
                elif 'sample' in case:
                    document = ROOT / 'sample_documents' / case['sample']
                else:
                    document = workdir / (case['title'] + '.md')
                    document.write_text(case['text'], encoding='utf-8')
                worker = Worker()
                try:
                    workspace = str(workdir / 'working.db')
                    extracted, _ = run(worker, action='summary', path=str(document), workspace=workspace, memory_mb=256)
                    if extracted['event'] == 'error':
                        raise RuntimeError(extracted['message'])
                    started = time.perf_counter()
                    output, _ = run(worker, action='ai', path=str(document), workspace=workspace,
                        key=extracted['key'], content_hash=extracted['source']['content_hash'], memory_mb=768,
                        model_config=str(ROOT / config), diagnostics=True)
                    sentence = output.get('summary_text', '')
                    record = dict(model_config=config, case=case['id'], elapsed=round(time.perf_counter() - started, 3),
                        mode=output.get('mode'), summary=sentence, draft=output.get('draft_for_validation'),
                        topic_checks=[any(term.lower() in sentence.lower() for term in group) for group in case['topics']],
                        peak_model_rss_mb=output.get('model_peak_rss_mb'), error=output.get('message'))
                    results.append(record)
                    print(json.dumps(record, ensure_ascii=True), flush=True)
                finally:
                    worker.stop()
    (ROOT / 'docs' / 'reports' / 'quality-comparison-source-selection.json').write_text(json.dumps(dict(
        method='AI source-sentence selection; keyword checks are diagnostics, not a semantic accuracy score',
        cpu_threads=2, memory_ceiling_mb=2048, result_cache=False, results=results), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
