# Validation reports

| Report | Scope |
| --- | --- |
| [ai-benchmark.json](ai-benchmark.json) | CPU inference on bundled browsing samples |
| [source-selection-check.json](source-selection-check.json) | Seven multilingual cases: parser text and anchor preservation |
| [benchmark-results.json](benchmark-results.json) | Full generated page/file corpus matrix |
| [benchmark-2gb.json](benchmark-2gb.json) | Quick benchmark with a 2 GiB process-tree limit |

Reports are measured snapshots. Some predate the English interface and retain raw Korean fixture text and original filenames. Source preservation does not measure representative selection or source truth. Local process limits do not establish actual 4 GB machine compatibility. Reproduce measurements using the [script guide](../../scripts/README.md).
