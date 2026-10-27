from __future__ import annotations

import re
import time
import uuid
from typing import Protocol

from .detect import language, natural_text
from .parsers import segments
from .store import identity, stamp, init_state

EVIDENCE_POLICY = '''Use only supplied evidence. Do not invent missing facts.
Preserve numbers exactly. Preserve names exactly. Preserve dates exactly.
If uncertain, omit the claim. Do not infer facts not supported by the document.'''

SUMMARY_CHAR_LIMIT = 200


def one_sentence(text):
    """Validate the result as one short sentence, without cropping a claim."""
    if re.search(r'<think>|```|(?m:^\s*(?:[-*•]\s|\d+[.)]\s|\[\d+\]))', text):
        return None
    text = re.sub(r'^\s*(?:요약|핵심\s*근거|Summary|Main\s+evidence)\s*[:：]\s*', '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip().strip('"“”')
    if not text or len(text) > SUMMARY_CHAR_LIMIT or not text.endswith(('.', '!', '?', '。')):
        return None
    if len(re.split(r'(?<=[.!?。])\s+(?=\S)', text)) != 1:
        return None
    return text


def extractive_sentence(evidence):
    """Choose one complete source sentence for quick/emergency display."""
    best, best_score = None, -1000
    for item in evidence:
        for sentence in source_sentences(item['text']):
            _, score = representative(sentence)
            if score > best_score:
                best_score = score
                best = dict(item, text=sentence, evidence=item['text'],
                            origin='extractive', facts=facts(sentence), verification='source_sentence')
    return best


def normalize_source(text):
    """Only layout whitespace may change; never rewrite words or punctuation."""
    return re.sub(r'\s+', ' ', text).strip()


def source_sentences(text):
    """Yield complete short source spans, retaining negation and qualifiers."""
    for paragraph in re.split(r'\n\s*\n', text):
        source = normalize_source(paragraph)
        matches = re.finditer(r'.+?(?:[.!?。](?=\s|$)|$)', source)
        for match in matches:
            sentence = match.group(0).strip()
            if not 12 <= len(sentence) <= SUMMARY_CHAR_LIMIT:
                continue
            if not sentence.endswith(('.', '!', '?', '。')):
                # A standalone slide bullet is allowed; a cropped trailing
                # fragment or all-capitals page heading is not.
                if sentence != source or len(source) > SUMMARY_CHAR_LIMIT or sentence.isupper():
                    continue
            if re.match(r'^(?:[-*•]\s|\d+[.)]\s|\[\d+\])', sentence):
                continue
            yield sentence


class SummaryModel(Protocol):
    model_id: str
    model_version: str
    context_tokens: int

    def summarize(self, evidence: str) -> str: ...


def facts(text):
    numbers = re.findall(r'(?<!\w)[₩$€£]?\d[\d,]*(?:\.\d+)*(?:[-/]\d+)*(?:\s?(?:%|원|달러|명|개|kg|km|GB|MB))?', text)
    names = re.findall(r'\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3}\b|[가-힣]{2,8}(?:주식회사|대학교|공사|연구원)', text)
    return {'numbers_dates': numbers[:32], 'names': names[:16]}


def verify_claim(claim, evidence):
    # Exact extraction is the strongest verification in lightweight mode.
    return claim in evidence and all(item in evidence for values in facts(claim).values() for item in values)


def representative(text, heading=False):
    sentences = re.split(r'(?<=[.!?。])\s+|\n+', text)
    best, best_score = '', -1000.0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        visible_length = len(re.sub(r'\s+', ' ', sentence))
        score = min(visible_length, 260) / 100
        score += 2 * bool(re.search(r'요약|결론|핵심|목표|결정|증가|감소|conclusion|summary|result|recommend', sentence, re.I))
        score += min(2, len(facts(sentence)['numbers_dates']) * .3)
        score -= 100 if heading else 0  # A heading is a fallback, never better than its body.
        if len(sentence) > 700:
            score -= 4
        if score > best_score:
            start = text.find(sentence)
            # Give the small model a useful contiguous evidence window, including
            # surrounding factual sentences rather than only a short label.
            best, best_score = (text if len(text) <= 700 else text[start:start + 700]).strip(), score
    return best, best_score


def section_page(db, key, offset=0, limit=24):
    rows = db.execute('SELECT section, anchor, excerpt FROM sections WHERE key=? ORDER BY position LIMIT ? OFFSET ?', (key, limit, offset)).fetchall()
    return [dict(section=s, anchor=a, text=t, facts=facts(t)) for s, a, t in rows]


def overview(db, key):
    count = db.execute('SELECT count(*) FROM sections WHERE key=?', (key,)).fetchone()[0]
    if count <= 12:
        return section_page(db, key, 0, 12), count
    # Reserve coverage positions, then include globally salient major sections.
    # A conclusion between the sampled positions must not disappear before AI.
    selected = {}
    for i in range(6):
        offset = round(i * (count - 1) / 5)
        row = db.execute('SELECT section, anchor, excerpt, position FROM sections WHERE key=? ORDER BY position LIMIT 1 OFFSET ?',
                         (key, offset)).fetchone()
        selected[row[0]] = row
    rows = db.execute('''SELECT section, anchor, excerpt, position FROM sections WHERE key=?
        ORDER BY score + CASE WHEN section LIKE '%결정%' OR section LIKE '%결론%' OR section LIKE '%요약%'
        OR lower(section) LIKE '%decision%' OR lower(section) LIKE '%conclusion%'
        OR lower(section) LIKE '%summary%' THEN 12 ELSE 0 END DESC, position LIMIT 12''', (key,))
    for row in rows:
        if len(selected) >= 12:
            break
        selected[row[0]] = row
    return [dict(section=s, anchor=a, text=t, facts=facts(t)) for s, a, t, _ in sorted(selected.values(), key=lambda row: row[3])], count


def summarize(path, kind, db, info, notify=lambda event: None):
    if not kind.summarizable:
        raise ValueError('검증된 문서만 요약할 수 있습니다.')
    init_state(db)
    _, source, before = identity(path)
    key = uuid.uuid4().hex  # A request identifier, never a reusable cache key.
    db.execute('DELETE FROM sections')
    db.commit()
    preview, quick, position, blank = '', [], 0, 0
    last_notice = time.monotonic()
    for segment in segments(path, kind):
        position += 1
        if not segment.text.strip():
            blank += 1
            continue
        if kind.format in ('text', 'markdown') and len(segment.text) > 500:
            if not natural_text(segment.text):
                db.rollback()
                raise ValueError('문서 내부에서 코드·설정·기계 데이터가 감지되어 요약을 중단했습니다.')
        if len(preview) < 48000:
            preview += '\n[%s]\n%s\n' % (segment.anchor, segment.text[:48000 - len(preview)])
        excerpt, score = representative(segment.text, segment.heading)
        if excerpt and verify_claim(excerpt, segment.text):
            db.execute('''INSERT INTO sections(key,section,position,anchor,excerpt,score) VALUES(?,?,?,?,?,?)
                ON CONFLICT(key,section) DO UPDATE SET anchor=excluded.anchor, excerpt=excluded.excerpt,
                score=excluded.score WHERE excluded.score>sections.score''',
                (key, segment.section, position, segment.anchor, excerpt, score))
            if len(quick) < 3:
                quick.append(dict(section=segment.section, anchor=segment.anchor, text=excerpt, facts=facts(excerpt)))
                notify(dict(event='quick', bullets=list(quick), complete=False))
        if position % 100 == 0:
            db.commit()
        if time.monotonic() - last_notice > .5:
            notify(dict(event='progress', message='%s개 구간 처리 중' % position))
            last_notice = time.monotonic()
    if stamp(path) != before:
        db.rollback()
        db.execute('DELETE FROM sections WHERE key=?', (key,))
        db.commit()
        raise ValueError('요약 중 원문이 변경되었습니다. 결과를 폐기했습니다.')
    if not preview.strip():
        raise ValueError('추출 가능한 텍스트가 없습니다. 스캔 PDF는 OCR이 필요합니다.')
    info['language'] = language(preview)
    db.commit()
    bullets, count = overview(db, key)
    return dict(key=key, info=info, bullets=bullets, sections=count, preview=preview[:48000],
                source=source, complete=True, empty_pages=blank)
