# Implementation and validation scope

Summary and extraction caching are disabled by the user's later instruction, overriding those parts of `AGENTS.md`. Each request processes the source again. Only temporary evidence for the current job is stored.

## Implemented

Folder browsing; name, path, and content search; file identity cards; safe text previews; document-only extractive selection; source locations; preliminary and complete states; paginated section evidence; source checks for numbers, names, and dates; change detection; cancellation; worker isolation; and OS memory ceilings.

Directory queues and section evidence are disk-backed. Thousands of pages are processed page by page. Source code is never sent to the model. Embeddings and automatic background document summaries are disabled.

Explicit AI requests use Qwen3 0.6B Q4_K_M on CPU. Because lexical and numeric checks missed semantic distortions in generated summaries, the model now selects only a source sentence ID. Input is verified at no more than 1,400 tokens within a 2K context; output is limited to eight tokens. The app copies one verified source sentence. mmap, Q8 KV, one slot, two threads, and low CPU priority remain enabled. The model is released after each job. Source truth and representative selection are separate quality concerns.

The interface, messages, documentation, and browsing samples use English. Korean regression documents remain in `tests/fixtures/korean`; Korean language patterns and historical raw outputs preserve multilingual coverage and measurement integrity.

## Local verification

- Unit tests cover spoofed files, extensionless PDF/Office detection, code/log/configuration disguised as text, malformed XML, XLSX shared strings and sheet names, PPTX note relationships, fresh processing on every request, temporary-workspace replacement, modified-file rejection, late-section retention, paginated file lists, and worker termination and reuse.
- Real Tk widget checks cover browsing, identity cards, summaries, evidence pagination, disabled summaries for source code, name/content search, 20 rapid navigation requests, bounded snapshot cleanup, recomputation, and workspace deletion on selection changes.
- The AI UI check runs ten Tk callbacks during real CPU inference, cancels and unloads the model, completes inference, recomputes a repeat request, and falls back to a source excerpt after an injected AI error. It checks the one-result display and source preservation.
- [AI benchmark](reports/ai-benchmark.json): actual CPU inference on bundled samples under a combined 2 GiB process-tree limit.
- [Source selection check](reports/source-selection-check.json): seven Korean/English synthetic cases, matched against original parser text and anchors. Tests reject changed numbers, dates, negation, tense, joined sentences, arbitrary prose responses, and invalid candidate IDs.
- [Full local benchmark](reports/benchmark-results.json) and [2 GiB process test](reports/benchmark-2gb.json): synthetic text PDFs and generated corpora. These are not scanned-PDF or real organizational-document quality evaluations.
- [Historical experiments](archive/README.md) compare two small models under matching CPU/context budgets. Keyword checks are diagnostics, not semantic accuracy scores.

Native Windows screenshot automation was unreliable, so screenshot-based layout verification has not been completed. Real Tk execution and widget behavior are checked by integration scripts.

### English interface verification, October 28, 2026

All 31 unit tests and the real Tk browsing/search/summary check passed after the language and file-layout changes. English action buttons fit at both the default 1400 by 900 and minimum 1120 by 740 window sizes. Documentation links resolve, and application/script/test modules compile. Recorded reports were relocated without changing their measured contents.

The AI UI check confirmed the low-memory fallback. Actual model inference was skipped because available system RAM was about 1 GiB, below the 1,280 MiB guard. Earlier AI reports remain historical measurements; this language change does not claim a new inference benchmark.

### DPI and UI scaling

`scripts/ui_scale_smoke.py` exercises real Tk widgets with simulated DPI factors of 1.0, 1.25, 1.5, and 2.0 and application zoom at 100%, 125%, and 150%. It checks visible controls and document text, the sidebar title and every sidebar child at the minimum 1120 by 740 window size, a compact-screen layout, font/row-height consistency, repeated zoom without rounding drift, unchanged summary contents/workspace during zoom, and settings restoration. These simulated factors do not replace visual testing on physical displays with different Windows DPI settings.

The application enables system DPI awareness before creating Tk windows. Named pixel fonts and logical layout metrics share one scale factor; large zoom is limited to the available work area. Reference behavior: [Windows DPI awareness](https://learn.microsoft.com/en-us/windows/win32/hidpi/setting-the-default-dpi-awareness-for-a-process) and [Tk font sizes](https://web.tcl.tk/man/tcl8.7/TkCmd/font.html).

## Outstanding

- An actual 4 GB VM, physical machine, or remotely executed CI container. Local 4 GB/2 GB process limits do not reproduce a complete constrained system. The local Docker daemon was unavailable during earlier validation.
- User evaluation on real documents and broader corpora. Exact quotations can still omit context or be poorly selected.
- Page-streamed scanned-document OCR and safe parsers for legacy DOC/PPT/XLS/HWP and RTF.
- Complete formula/chart interpretation, PDF table-layout recovery, and advanced structural/category detection for every format. Uncertain categories remain `Unknown`.
- End-to-end injection of real disk exhaustion, parser OOM from large hostile documents, and network-drive delays. Existing checks cover allocation denial, worker termination/cancellation, source modification, and observed AI RSS-budget failure.

The complete Definition of Done in `AGENTS.md` has not been achieved. The project provides a working explorer and reproducible validation tools with these stated limits.
