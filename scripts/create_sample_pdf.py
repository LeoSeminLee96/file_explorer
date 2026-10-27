"""Generate a small, genuinely readable PDF fixture without external fonts."""
from pathlib import Path
import fitz

root = Path(__file__).resolve().parents[1]
document = fitz.open()
sections = [
    ('DOCUMENT WORKSPACE', 'A quieter way to work with your documents.',
     'Local files. Clear sources. Bounded memory.\nThis sample document contains fictional product planning material.'),
    ('01 / EXPLORER FIRST', 'Finding a file should always feel immediate.',
     'The target device has 4 GB of RAM.\nOnly 160 file rows are rendered at a time.\nDirectory metadata is stored on disk rather than in an unbounded list.'),
    ('02 / EVIDENCE MATTERS', 'Every summary starts with its source.',
     'A source card identifies the filename, type, full path, size and timestamps.\nImportant statements keep their original page anchors.\nNumbers and dates are copied exactly from the source.'),
    ('03 / CONCLUSION', 'Small working sets, useful results.',
     'The parser runs in an isolated process with a 256 MB ceiling.\nThe document is processed page by page.\nThe final section must remain represented in the summary.'),
]
for index, (eyebrow, title, body) in enumerate(sections):
    page = document.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 842), color=None, fill=(.97, .98, .97))
    page.insert_text((54, 72), eyebrow, fontsize=10, color=(.03, .45, .4))
    page.insert_textbox(fitz.Rect(54, 146, 540, 330), title, fontsize=32, fontname='hebo', color=(.13, .19, .22))
    page.draw_line((54, 358), (540, 358), color=(.7, .8, .77))
    page.insert_textbox(fitz.Rect(54, 400, 530, 650), body, fontsize=13, lineheight=1.7, color=(.3, .37, .4))
    page.insert_text((54, 790), 'DOCUMENT EXPLORER  /  LOCAL WORKSPACE', fontsize=8, color=(.4, .5, .5))
    page.insert_text((520, 790), str(index + 1), fontsize=10)
document.set_metadata({'title': 'Document Workspace - Product Brief', 'author': 'Document Explorer'})
target = root / 'sample_documents' / '06_Product_Brief.pdf'
document.save(target, deflate=True)
document.close()
print(target)
