"""Search and preview example. Source code never enters document summarization."""


def find_document(filename, query):
    return query.casefold() in filename.casefold()


MAX_VISIBLE_FILES = 160
PREVIEW_CHARACTER_LIMIT = 24000
