# Document Explorer

A local document explorer for Windows with folder browsing, filename and path search, document and source-code content search, file details, text previews, and optional small CPU AI. Files stay on your computer. Browsing and search work without a model.

## Run

Double-click **`run.bat`**. On a new installation, use Python 3.9 or later with Tk and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

To open a specific folder:

```powershell
.\.venv\Scripts\python.exe app.py "D:\Documents"
```

PyMuPDF is required for PDF previews and extraction. Browsing, text search, and Office document extraction work without it. Launch with `--no-ai` to select source text without loading a model.

## Use

- **Open folder** or enter a path to navigate. Double-click a folder to open it.
- **Name / path** filters the file list. Enable **Subfolders** to search recursively.
- **File contents** streams document and source-code content search. Results are limited to 160 rows; selecting a file stops the search and opens its preview.
- **Documents** filters candidate extensions. Actual format and parser availability are validated when a file is selected.
- Select a file to see its full path, size, modified and created times, actual format, title, length, language, and category. Unavailable details appear as `Unknown`.
- **AI excerpt** asks the model to select one source sentence. The app displays that sentence verbatim, with its source location. **Lightweight summary** selects a sentence using deterministic ranking when AI is unavailable.
- Use the arrows below a completed result to inspect evidence from individual sections.
- **Cancel** or `Esc` stops parsing, search, or AI. Selecting another file cancels the previous document job.

Shortcuts: `Ctrl+F` search, `Ctrl+L` address, `Alt+Left` back, `Alt+Up` parent folder, `F5` refresh.

**UI scale** in the top-right corner controls text and layout together. `Auto` follows the Windows startup DPI; 90%, 100%, 110%, 125%, and 150% adjust that size. Use `Ctrl++` / `Ctrl+-` to change zoom or `Ctrl+0` to restore Auto. The preference is saved. Fonts, spacing, controls, and table rows scale together. If the requested size exceeds the available screen, `UI scale (fit)` indicates an automatic fit limit. Narrow layouts hide the sidebar; the toolbar's **Open** button and address bar remain available.

The interface, messages, documentation, and bundled browsing samples are in English. Korean document detection, search, and source preservation remain supported. Korean text in regression fixtures, language heuristics, and recorded benchmark outputs is intentional.

## Supported formats

| Format | Preview / summary | Extraction |
| --- | --- | --- |
| PDF | Supported | Signature and parser validation; page-by-page text |
| DOCX | Supported | Heading styles, paragraphs, table paragraphs |
| PPTX | Supported | Slides, related speaker notes, chart text |
| XLSX | Supported | Sheet names, ranges, headers, formula counts, numeric statistics; disk-backed shared strings |
| HWPX | Supported | Section XML and paragraphs |
| ODT / ODP / ODS | Supported | Headings, paragraphs, slides, sheets |
| TXT / Markdown | Natural-language documents only | Heuristics exclude code, configuration, logs, and dumps |
| DOC / PPT / XLS / HWP / RTF | Summary unavailable | Convert to a supported format; no safe parser is included |
| Source code / configuration | Search and text preview | Summary disabled |
| Executables / images / other binary files | Metadata | Summary disabled |

Scanned-PDF OCR and encrypted-document unlocking are not included. Spreadsheet results select programmatically extracted information from cells, ranges, and formulas.

## Optional CPU model

Install the model explicitly:

```powershell
.\.venv\Scripts\python.exe scripts/setup_ai.py
```

The installer downloads an official [Qwen3 0.6B GGUF](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF) Q8_0 model, verifies source and runtime SHA256 hashes, and requantizes it locally to **Q4_K_M** using CPU-only llama.cpp. The installed model is approximately **378 MiB**. Requantization is not assumed to match direct quantization from original training weights. Installation needs internet access; inference runs locally. Assets are stored in `.data/ai`, with configuration in `.data/model.json`.

- Two CPU threads, one inference slot, no GPU offload, low process priority.
- Fixed 2,048-token context; tokenizer-verified input of at most 1,400 tokens.
- Streaming extraction selects structural evidence and up to 12 complete source sentences, each at most 200 characters. The model returns one sentence ID, constrained by grammar and an eight-token output budget. Display text comes from the source candidate, never the model response.
- Native chat template with thinking disabled. Oversized input drops whole candidates. Sentences, conditions, and negations are never cropped to fit. Documents without suitable short sentences report an explicit limitation.
- mmap loading, Q8 KV cache, and disabled weight repacking. The worker process tree has a 768 MiB commit/address-space ceiling, with a separate sampled combined-RSS watchdog. AI is skipped below 1,280 MiB of available RAM.
- A private authenticated `127.0.0.1` endpoint, no web UI, automatic download, or prompt reuse. The model is unloaded on completion, cancellation, or file selection changes.

This is **AI-assisted extractive selection**. It prevents model-written changes to numbers, names, negation, and tense from reaching the display. Only whitespace is normalized. It does not establish that the source is true, that the sentence represents the entire document, or that surrounding context is unnecessary. See the [source preservation report](docs/reports/source-selection-check.json) and [quality review](docs/summary-quality.md).

`SummaryModel` and `LlamaCppModel` provide the adapter boundary. `scripts/setup_candidate.py` installs an optional comparison model; it does not replace the default. Earlier free-generation trials were insufficiently reliable and are preserved in [the experiment archive](docs/archive/README.md).

## No summary cache

Every request rereads the source and reruns extraction and selection. Summary and extraction results are not reused across requests. Legacy `.data/documents.db` files are removed on startup.

Large-document evidence is held in a temporary SQLite workspace for the current selection. It is deleted on reselection, cancellation, another summary request, or normal exit. File-list metadata and the last folder setting persist separately. Model weights and runtime executables are installed application assets.

## Memory design

Explorer/search take priority over preview, parsing, and AI. Startup detects physical and container memory limits and selects an ULTRA LOW, LOW, NORMAL, or HIGH profile.

File listings and recursive directory queues are disk-backed. The UI displays at most 160 rows. One scan thread keeps only the latest navigation request. One isolated parser runs on demand, with an OS-enforced 256 MiB budget, reduced to 128 MiB under memory pressure. If the limit cannot be applied, parsing stops safely.

PDF extraction is page-based, XML uses streaming parsing, and text read buffers are 16 KiB. Oversized ZIP directories and encrypted or oversized entries are rejected. Previews are capped at 24,000 characters. Section evidence remains on disk; the overview shows up to 12 representative sections selected for importance and document coverage. Parser and AI failures are isolated from the UI. No embedding model or automatic background summarization is started.

## Project layout

```text
app.py                    Tk desktop interface
explorer/                 Detection, parsers, search, summaries, worker isolation
scripts/                  Setup, UI checks, and benchmark entry points
sample_documents/         English browsing examples
tests/                    Unit and failure tests
tests/fixtures/korean/    Korean regression documents
docs/                     Architecture, validation, and quality notes
docs/reports/             Recorded validation and performance results
docs/archive/             Historical model experiments
.github/workflows/        Constrained-memory CI definition
.data/                    Ignored local models, settings, indexes, generated fixtures
```

See the [script guide](scripts/README.md), [validation scope](docs/validation.md), and [architecture requirements](AGENTS.md).

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe scripts/ui_smoke.py
.\.venv\Scripts\python.exe scripts/ui_scale_smoke.py
.\.venv\Scripts\python.exe scripts/ui_ai_smoke.py
.\.venv\Scripts\python.exe scripts/benchmark_ai.py
.\.venv\Scripts\python.exe scripts/check_source_summary.py
.\.venv\Scripts\python.exe scripts/benchmark.py --limit-mb 4096
.\.venv\Scripts\python.exe scripts/benchmark.py --quick --limit-mb 2048 --output docs/reports/benchmark-2gb.json
```

AI checks require an installed model. The full benchmark generates 1, 10, 100, 500, 1,000, and 5,000-page PDFs and 100, 10,000, and 100,000-file corpora under `.data/benchmarks`. Reports record time to first and complete summary, repeat-request processing time, RSS, CPU time, process read bytes, numeric preservation, evidence matches, and section coverage. Process reads can include I/O served from the OS cache.

Local process-tree limits **do not replace testing an actual 4 GB system**. The [CI workflow](.github/workflows/constrained.yml) caps container memory and total memory-plus-swap at 4 GB; its remote run has not yet been completed. Full compatibility is not claimed.
