from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .memory import constrain_process


def emit(data):
    print(json.dumps(data, ensure_ascii=True), flush=True)


def inspect_file(path):
    from .detect import detect, language
    from .parsers import metadata, segments
    from .store import stamp
    before = stamp(path)
    kind = detect(path)
    info = metadata(path, kind)
    preview = ''
    if kind.parser or kind.format in ('code', 'text', 'markdown'):
        for segment in segments(path, kind):
            preview += '[%s]\n%s\n\n' % (segment.anchor, segment.text[:24000 - len(preview)])
            if len(preview) >= 24000:
                break
        info['language'] = language(preview)
    if stamp(path) != before:
        raise ValueError('파일이 변경되었습니다. 다시 선택하세요.')
    # Parser validation must complete before Summary is enabled in the UI.
    emit(dict(event='inspected', kind=kind.dict(), info=info, preview=preview[:24000], stamp=before))


def content_search(request):
    from .detect import detect, NEVER, SOURCE
    from .parsers import segments
    from .files import file_db, scan
    root, query = Path(request['path']), request['query'].casefold()
    filename = request['search_db']
    scan(root, filename, request.get('recursive', False), progress=lambda n: emit(dict(event='progress', message='%s개 파일 탐색 중' % n)))
    db = file_db(filename)
    try:
        matches, scanned, last = 0, 0, time.monotonic()
        cursor = db.execute('SELECT path FROM files WHERE directory=0 ORDER BY name')
        for (name,) in cursor:
            path = Path(name)
            scanned += 1
            try:
                # No LLM is involved: source code is searchable as bounded text.
                kind = detect(path)
                if not kind.parser and kind.format not in ('text', 'markdown', 'code'):
                    continue
                for segment in segments(path, kind):
                    position = segment.text.casefold().find(query)
                    if position >= 0:
                        stat = path.stat()
                        snippet = segment.text[max(0, position - 50):position + 150].replace('\n', ' ')
                        emit(dict(event='match', path=str(path), name=path.name, size=stat.st_size, modified=stat.st_mtime,
                                  extension=path.suffix, anchor=segment.anchor, snippet=snippet))
                        matches += 1
                        break
                if matches >= 160:
                    break
            except MemoryError:
                raise
            except Exception:
                # A bad document cannot abort a corpus search.
                pass
            if time.monotonic() - last > .5:
                emit(dict(event='progress', message='%s개 검사 · %s개 일치' % (scanned, matches)))
                last = time.monotonic()
        emit(dict(event='search_done', matches=matches, scanned=scanned, limited=matches >= 160))
    finally:
        db.close()


def main():
    request = json.loads(sys.stdin.readline())
    if not constrain_process(request.get('memory_mb', 256)):
        emit(dict(event='error', message='OS 메모리 제한을 설정하지 못해 안전하게 처리를 중단했습니다.'))
        return
    try:
        path = Path(request['path'])
        action = request['action']
        if action == 'ai':
            from .ai import LlamaCppModel, load_config
            from .detect import detect
            from .store import connect, identity, stamp
            from .summary import overview
            kind = detect(path)
            if not kind.summarizable:
                raise ValueError('검증된 문서만 AI에 전달할 수 있습니다.')
            _, source, before = identity(path)
            if source['content_hash'] != request['content_hash']:
                raise ValueError('문서 추출 이후 원문이 변경되었습니다.')
            config = load_config(request.get('model_config'))
            if not config:
                raise ValueError('사용 가능한 소형 CPU 모델이 없습니다.')
            if request.get('diagnostics'):
                config['diagnostics'] = True
            config['document_title'] = path.stem
            db = connect(request['workspace'])
            try:
                evidence, count = overview(db, request['key'])
            finally:
                db.close()
            if not evidence:
                raise ValueError('AI 요약을 위한 문서 근거가 없습니다.')
            emit(dict(event='progress', message='소형 CPU 모델 로드 중 · 단일 작업 / 컨텍스트 2K'))
            started = time.perf_counter()
            with LlamaCppModel(config, Path(request['workspace']).parent) as model:
                emit(dict(event='progress', message='AI가 핵심 원문 문장을 선택 중 · 문장 생성 없이 출처 그대로 표시합니다'))
                result = model.summarize(evidence)
            if stamp(path) != before:
                raise ValueError('AI 처리 중 원문이 변경되었습니다. 결과를 폐기했습니다.')
            emit(dict(event='ai_summary', **result, total_ai_seconds=time.perf_counter() - started))
        elif action == 'inspect':
            inspect_file(path)
        elif action == 'search':
            content_search(request)
        else:
            from .detect import detect
            from .parsers import metadata
            from .store import connect, init_state
            from .summary import summarize, section_page
            db = connect(request['workspace'])
            try:
                init_state(db)
                if action == 'sections':
                    emit(dict(event='sections', bullets=section_page(db, request['key'], request.get('offset', 0)), offset=request.get('offset', 0)))
                else:
                    kind = detect(path)
                    result = summarize(path, kind, db, metadata(path, kind), emit)
                    emit(dict(event='summary', **result))
            finally:
                db.close()
    except MemoryError:
        emit(dict(event='error', message='메모리 한도에 도달했습니다. 작업을 중단했습니다. 파일 탐색은 계속 사용할 수 있습니다.'))
    except Exception as error:
        emit(dict(event='error', message=str(error)[:500] or type(error).__name__))


if __name__ == '__main__':
    main()
