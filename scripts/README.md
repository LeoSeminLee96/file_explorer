# Project scripts

Run scripts from the project root using `.venv\Scripts\python.exe` on Windows.

| Script | Purpose |
| --- | --- |
| `setup_ai.py` | Explicitly install and verify the default small CPU model/runtime |
| `setup_candidate.py` | Install the optional comparison model; does not change the default |
| `create_sample_pdf.py` | Generate the bundled English product brief |
| `ui_smoke.py` | Check real Tk navigation, identity, search, summaries, and cleanup |
| `ui_scale_smoke.py` | Check DPI/zoom geometry, minimum-window clipping, reversible scaling, and saved settings; `--review` opens a temporary review window |
| `ui_ai_smoke.py` | Check actual CPU inference, UI responsiveness, cancellation, and fallback |
| `benchmark.py` | Generate and measure the page/file corpus matrix |
| `benchmark_ai.py` | Measure the installed model on English browsing samples |
| `check_source_summary.py` | Verify seven multilingual source sentences and anchors |
| `compare_quality.py` | Compare models; keyword checks are diagnostic |

Results go to `docs/reports/`. Generated corpora and local model assets go to ignored `.data/`. Historical experiments are under `docs/archive/`.
