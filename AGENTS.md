# Ultra-Low-Memory Document Intelligence Requirements

The application must support file browsing, search, preview, and document summaries on low-end PCs with 4 GB RAM or less. AI must never compromise the explorer's basic performance.

```text
Explorer/Search > Preview > Document Parsing > AI Summary
```

Under memory pressure, reduce or disable AI first and preserve browsing and search.

**Current project override:** the user's later instruction disables summary and extraction result caching. Sections 9, 29, 32, 33, 40, 51, and the original cache-related acceptance criterion describe the original architecture; do not reintroduce result caching. Bounded temporary working state for the current request is allowed and must be cleaned up. Model assets and file-list metadata are separate from summary results.

## 1. Summary is document-only

AI summaries are available only for documents. Exclude source code, executables, DLL/shared libraries, archives, disk images, databases, binary data, models, images, video, audio, fonts, system files, configuration, and temporary files.

Examples: `.rs .py .js .ts .java .cpp .c .h .go .cs .php .rb .swift .kt`, `.exe .dll .so .dylib`, `.zip .7z .rar .tar`, `.db .sqlite`, `.gguf .onnx`, `.iso .bin`.

Search and metadata remain allowed for these files. Preview is allowed when safe. AI summary is prohibited.

## 2. Long source code must never enter an LLM

Source files with 1,000, 100,000, or 1,000,000 lines must never enter the summarization pipeline. Provide filename, path, full-text, symbol-like text search, preview, and metadata only. Large repositories must not bottleneck the LLM worker.

## 3. Document allowlist

Candidates include PDF; DOC/DOCX/ODT/RTF; HWP/HWPX; PPT/PPTX/ODP; XLS/XLSX/ODS; TXT and Markdown. An extension alone is insufficient to identify a document.

## 4. Strict document identification

Combine extension, magic bytes, MIME/content signature, container structure, and parser validation. Renaming `report.exe` to `report.pdf` must not make it a PDF. Valid signatures must identify formats even without an extension.

## 5. Plain-text classification

Natural-language TXT/Markdown such as meeting notes, reports, articles, manuals, proposals, research notes, and documentation may be summarized. Text that is effectively code, a hex dump, machine log, generated data, or configuration must be excluded.

Use inexpensive heuristics: natural-language ratio, line-length and punctuation distributions, code-token ratio, bracket ratio, identifier density, and entropy. Never run an LLM for classification.

## 6. Document identity card

Before a summary, show filename, actual file type, full path, size, modified time, created time, document title, page/slide/sheet count, detected language, and category. Users must always know which file a result belongs to.

Example: `2026_AI_Security_Report.pdf`, PDF Document, `D:\Research\Security\`, 8.7 MB, 127 pages, Korean/English, Technical Report, modified 2026-10-21.

## 7. Document type identification

Identify Research Paper, Technical Report, Business Report, Manual, Contract, Proposal, Presentation, Spreadsheet, Meeting Notes, Article, or General Document when supported. Do not guess: `Document Type: Unknown` is valid. Prefer metadata and structure over LLM classification.

## 8. Summary header

Every AI result must include source identity: filename, type/category, page count, and modified time. Prevent results from one file appearing for another.

## 9. Summary cache identity

Original cache requirement, superseded by the current no-cache instruction: never key by filename alone. A cache would require stable file ID, content hash, file size, modified time, model ID/version, prompt version, and summary mode. Changed files must never reuse old results.

## 10. 4 GB RAM is a primary target

Do not consume all system RAM. Explorer-only memory must be extremely low. Search and preview must be bounded; extraction uses bounded streaming buffers. Load AI only when explicitly needed.

## 11. Memory profiles

Detect system memory and select a startup profile:

| Profile | System RAM |
| --- | --- |
| ULTRA LOW | Up to 4 GB |
| LOW | Above 4 GB, up to 8 GB |
| NORMAL | Above 8 GB, up to 16 GB |
| HIGH | Above 16 GB |

## 12. Ultra-low profile

For systems with at most 4 GB: one AI worker, one parser worker, no large preview cache, no embedding model, semantic index disabled by default, no background AI summaries, and no parallel document summarization. Never put several documents into the LLM concurrently.

## 13. Small-model policy

Benchmark very small CPU-friendly quantized models, initially 0.5B to 0.8B parameters. Default to 4-bit quantization or a measured better memory/quality tradeoff. Do not assume a model of at least 1B is necessary.

## 14. Model adapter

Keep architecture independent of model names. A `SummaryModel` abstraction must support a small CPU model, alternative small models, and future models. Selection criteria: RAM, CPU latency, Korean/English quality, faithfulness, and binary/model size.

## 15. mmap-oriented loading

Prefer memory mapping where supported rather than forcing all weights resident. Do not default to `mlock` for the full model on systems with at most 4 GB. Use the OS page cache and measure memory pressure.

## 16. Small context is mandatory

Never build hundreds of thousands of tokens of context. A 500-page document must not become one prompt. Start benchmarks with a fixed 2K to 4K effective context and increase only when necessary.

## 17. Do not solve long documents with huge context

Do not address length by switching to 64K or 128K contexts. This increases RAM, prompt-processing latency, KV cache, and first-token latency. Use hierarchical processing instead.

## 18. Streaming document pipeline

```text
Document -> Streaming Parser -> Structural Segments -> Section Metadata
         -> Importance / Coverage Selection -> Bounded Summary Chunks
         -> Hierarchical Merge -> Final Summary
```

Never load the entire extracted document into RAM at once.

## 19. Structural segmentation

Prefer title, abstract, heading, subheading, paragraph, bullet list, table, caption, page, slide, and sheet boundaries. Use sentence/paragraph fallback only when document structure is unavailable. Do not simply split every N characters.

## 20. Source anchors

Retain original positions: PDF pages; PPTX slide numbers; DOCX headings and paragraph indices; XLSX sheet names and cell ranges.

## 21. Evidence-aware summary

Important claims and figures should remain traceable, for example revenue growth of 18% `[p. 12]` or supply-chain risk `[p. 48-50]`. Every sentence need not display a citation, but retain anchor support for important claims.

## 22. Accuracy before fluent hallucination

Never ask the model to fill missing facts. Prompts must require:

```text
Use only supplied evidence.
Do not invent missing facts.
Preserve numbers exactly.
Preserve names exactly.
Preserve dates exactly.
If uncertain, omit the claim.
Do not infer facts not supported by the document.
```

## 23. Numerical facts protection

Extract dates, money, percentages, measurements, version numbers, counts, and proper nouns separately. Prevent arbitrary changes; cross-check summary output against deterministic extraction where possible.

## 24. Fast first-pass summary

Do not leave an empty screen until an entire large document finishes. Use lightweight title, heading, abstract, executive-summary, conclusion, and high-value sentence extraction to show a `Quick Summary` first.

## 25. Refined summary

When more detail is needed, use section summaries, coverage validation, hierarchical reduction, and a final result. A fast result may precede a refined result. Clearly distinguish incomplete work from a completed summary.

## 26. Avoid an LLM call for every chunk

Do not blindly send every chunk of a 1,000-page document to the model. Select information using heading importance, section coverage, keyword/sentence scoring, position, title similarity, numeric density, and TF-IDF/BM25-like relevance.

## 27. Preserve coverage

Combine salience with structural coverage. Pure top-K selection can omit the end of a document. Retain at least one representative segment per major section; avoid 20 introduction chunks and no conclusion.

## 28. Adaptive hierarchical summarization

Short documents use one pass. Medium documents use section selection before summary. Long documents use section summaries and reduction. Extremely large documents use a hierarchy with bounded intermediate summaries and final synthesis.

## 29. Disk-backed intermediate state

Never retain all chunks and intermediate results in RAM. Spill chunk metadata, section evidence, anchors, and completion state to disk as needed; keep only a bounded working set. Under the current override, this is temporary request state, not a reusable result cache.

## 30. Many documents must not mean many models

Whether there are 10, 1,000, 100,000, or 1,000,000 documents, reuse one AI worker. Do not create a model instance per document.

## 31. Never summarize everything automatically

A filesystem scan may build metadata and content-search indexes; it must not automatically generate 100,000 LLM summaries. AI requires a user request or explicitly enabled background policy.

## 32. Summary cache

Original requirement: unchanged content hashes reused a cached result, changed content regenerated it. **Superseded:** every summary request must now reread and reprocess the source, even if unchanged.

## 33. Partial cache

Original requirement: consider document and section hashes to avoid regenerating unchanged sections in a 500-page document. **Superseded:** no cross-request partial-summary reuse.

## 34. Persistent, bounded work queue

Large batches must not create tens of thousands of in-memory tasks. Use a SQLite queue or bounded persistent scheduler, pulling only a small number of pending jobs into RAM for one AI worker.

## 35. User requests always win

Foreground work takes priority over background extraction/indexing:

1. UI interaction
2. Search
3. Preview
4. User-requested summary
5. Incremental indexing
6. Background extraction
7. Optional precomputation

## 36. Hard memory budget

Define an AI ceiling based on benchmarks. Never exhaust physical RAM; leave substantial memory for the OS, WebView/UI, filesystem cache, SQLite, and other applications. When the budget is exceeded, reduce context, reduce batch size, clear cache, switch model, then fall back to extractive selection.

## 37. Extractive emergency mode

When RAM is scarce or the model cannot load, use structural extraction and sentence ranking. Label it clearly, for example `Lightweight Summary`.

## 38. Unload AI when necessary

Do not keep the model resident indefinitely while the user resumes normal browsing. After an idle interval, release context and unmap or terminate the worker. Lazy-load it on the next request.

## 39. Avoid unnecessary document duplication in search indexes

The source already exists on disk. Benchmark FTS/index size, disk usage, and write amplification. Avoid multiple unnecessary copies of full documents.

## 40. Document extraction cache

Original requirement: reuse extraction for the same content hash and parser version without keeping all text in RAM. **Superseded:** extraction must run again for each request.

## 41. XLSX handling

Spreadsheets are not ordinary prose. Extract sheet names, used ranges, headers, tables, numeric columns, formulas, and summary statistics first. Pass only relevant bounded information to the model, never a million cells.

## 42. PPTX handling

Preserve slide structure and focus on slide titles, bullets, speaker notes, tables, and chart labels.

## 43. PDF handling

Preserve page boundaries, headings, paragraphs, and extractable tables. Scanned-PDF OCR needs a separate path and page-by-page streaming on 4 GB systems; never OCR the whole document at once.

## 44. DOCX/HWP handling

Preserve document titles, heading hierarchy, paragraphs, tables, and footnotes when possible. Do not discard meaningful structure in a plain-text dump.

## 45. Cancellation

Changing selection during a 1,000-page summary immediately removes its foreground priority. Cancel must safely stop current generation, parsing, and pending chunks, without leaving intermediate RAM or workers behind.

## 46. Performance benchmark matrix

Benchmark documents of 1, 10, 100, 500, 1,000, and 5,000 pages and corpora of 100, 10,000, and 100,000 documents. Measure time to first result, total summary time, peak RSS, CPU utilization, disk reads, summary quality, numeric accuracy, and section coverage. The original cache-hit metric is superseded by the no-cache policy; measure recomputation instead.

## 47. Test a real 4 GB environment

A successful run on a developer's 32/64 GB PC does not establish 4 GB compatibility. Execute at least one CI/VM/physical benchmark with actual total memory limited to 4 GB. If possible, also use a 2 GB constrained-process test to verify graceful degradation.

## 48. Required failure tests

The explorer must survive AI allocation failure, large PDF opening, a 5,000-page document, 100,000 indexed documents, rapid selection changes, parser OOM, AI worker termination, full working-state storage, and source modification during summarization.

## 49. UI policy

Documents offer Preview and Summary. Source code offers Preview and Search. Binary files focus on Metadata. Prevent unsupported summary requests in the UI.

## 50. Summary button visibility

After selection, detect the actual format. Hide or disable Summary for non-documents. For documents, enable it only after a safe parser is available and validated. Extension alone must not enable the button.

## 51. Final architectural rule

Do not solve long files by requiring more RAM, larger LLMs, bigger contexts, or more workers. Use streaming, structure awareness, bounded working sets, hierarchical processing, importance plus coverage, incremental processing, disk-backed state, one reusable AI worker, and a small quantized model. The original persistent-result-cache requirement is superseded by the no-cache policy.

File count, document length, and folder depth may increase total work, but must not cause unbounded growth in memory or interactive latency.

## Definition of Done

- Explorer runs on an actual 4 GB RAM system.
- No GPU is required.
- Browsing and search work without an AI model.
- AI summaries are available only for documents, never source code.
- Actual file formats are identified.
- Summary views show filename, type, and full path.
- Thousands of pages are processed without loading all text into RAM.
- Context is not increased arbitrarily for long documents.
- Section coverage is preserved.
- Major numbers, dates, and proper nouns have verification logic.
- Worker count does not grow with document count.
- Background discovery does not automatically summarize every document.
- Every request rereads and reprocesses the source; no reusable summary or extraction result cache (user override).
- AI OOM and parser OOM do not kill the explorer.
- Low memory allows extractive fallback.
- Benchmarks in an actual 4 GB constrained environment are complete.
