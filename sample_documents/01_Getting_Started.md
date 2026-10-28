# Welcome to Document Explorer

Document Explorer helps you find local files, inspect their contents, and read a short source excerpt. Files are not sent to an external server.

## Browse documents

Choose Open folder in the sidebar. Select a file to see its name, actual format, full path, size, modified time, and created time. Double-click a folder to open it.

Use Name / path to find filenames and locations. Enable Subfolders to search deeper folders. Select File contents to search inside documents and source code.

## Read a source excerpt

Select a document and choose Lightweight summary to rank its original sentences. Numbers, dates, and names are preserved in the chosen sentence. Evidence from document sections remains available separately.

With the small CPU model installed, AI excerpt asks the model to select one original sentence. The model returns only its number; the app displays the source text. Results are not cached, so every request processes the source again.

Preliminary and complete results are labeled separately. Select another file or press Escape to cancel the current document job.

## Supported formats

Supported documents include PDF, DOCX, PPTX, XLSX, HWPX, ODT, ODP, ODS, natural-language TXT, and Markdown. PDF extraction requires PyMuPDF. Scanned PDFs need separate OCR support.

Legacy DOC, PPT, XLS, HWP, and RTF have no safe summary parser in this app. Source code, executables, archives, images, and configuration files are excluded from summarization.
