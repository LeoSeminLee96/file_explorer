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

CASES = [
    dict(id='meeting', sample='02_제품_기획_회의.md', topics=[['검색'], ['미리보기']]),
    dict(id='metrics', sample='03_분기_운영_보고서.txt', topics=[['25%'], ['검토', '처리']]),
    dict(id='product_brief', sample='06_Product_Brief.pdf', topics=[['memory'], ['document', 'file']]),
    dict(id='privacy', title='파일 공유 정책 결정', topics=[['로컬'], ['승인', '수동', '자동 업로드하지']], text='''# 파일 공유 정책 결정

## 회의 개요
2026년 10월 20일 파일 공유 정책을 검토했습니다. 검토 중인 초안에는 자동 업로드 기능이 포함되어 있었습니다.

## 주요 결정
자동 업로드는 도입하지 않습니다. 사용자가 직접 승인한 파일만 공유하고, 나머지 문서는 로컬 저장소에 보관합니다. 외부 서버로 자동 전송하지 않는 수동 승인 방식을 채택합니다.

## 다음 단계
2026년 11월 3일 화면 시안을 검토할 예정입니다. 아직 기능을 출시하지 않았습니다.
'''),
    dict(id='streaming', title='대용량 문서 처리 설계', topics=[['스트리밍', '분할'], ['64KB', '메모리']], text='''# 대용량 문서 처리 설계

## 배경
기존 처리는 파일 전체를 메모리에 올려 대용량 문서에서 프로그램이 종료되는 문제가 있었습니다.

## 핵심 설계
문서를 64KB 버퍼로 나누어 읽는 스트리밍 방식을 사용합니다. 처리한 구간은 즉시 해제하고 파일 전체 텍스트를 메모리에 보관하지 않습니다. 입력 크기와 관계없이 작업 메모리를 제한합니다.

## 검증 계획
수천 페이지 문서에서 메모리 사용량을 측정할 예정이며 아직 운영 환경에 배포하지 않았습니다.
'''),
    dict(id='pilot', title='Local pilot decision', topics=[['local'], ['pilot'], ['20']], text='''# Local pilot decision

## Background
The team reviewed a cloud migration proposal during the planning meeting.

## Decision
The cloud migration was rejected. The team approved a local-only pilot for 20 users to evaluate document search. A production rollout has not been approved.

## Next steps
The pilot is scheduled to begin next month. It has not launched yet.
'''),
    dict(id='incident', title='Temporary storage incident', topics=[['disk', 'storage'], ['temporary', 'cleanup', 'cleaning']], text='''# Temporary storage incident

## Background
Document extraction failed on several workstations during a routine test.

## Conclusion
The failures were caused by a full temporary disk, not a network outage. Cleaning temporary files restored extraction. Read-only file browsing remained available during the incident.

## Prevention
The team will add a temporary storage usage check before starting extraction.
'''),
]


def main():
    assert constrain_process(2048), 'A real OS memory ceiling is required'
    results = []
    for config in ('.data/model.json', '.data/model-candidate.json'):
        for case in CASES:
            with tempfile.TemporaryDirectory(prefix='quality-', dir=ROOT / '.data') as temp:
                workdir = Path(temp)
                if 'sample' in case:
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
    (ROOT / 'docs' / 'quality-comparison-source-selection.json').write_text(json.dumps(dict(
        method='AI source-sentence selection; keyword checks are diagnostics, not a semantic accuracy score',
        cpu_threads=2, memory_ceiling_mb=2048, result_cache=False, results=results), ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
