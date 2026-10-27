"""검색과 미리보기 전용 예제. 소스코드는 문서 요약에 들어가지 않습니다."""


def find_document(filename, query):
    return query.casefold() in filename.casefold()


MAX_VISIBLE_FILES = 160
PREVIEW_CHARACTER_LIMIT = 24000
