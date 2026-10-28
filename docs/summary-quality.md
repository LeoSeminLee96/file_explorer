# Summary quality and source preservation

The current implementation asks AI to select a sentence ID and copies the corresponding source sentence into the UI. It does not use the earlier free-generation pipeline. The [source check](reports/source-selection-check.json) verifies exact text and anchor preservation, allowing whitespace normalization only.

## Why generation was replaced

Earlier trials with Qwen3 0.6B Q4_K_M and Qwen3.5 0.8B Q4_0 produced semantic mistakes even when numbers and vocabulary overlapped with the evidence. Examples included joining dates from different events, implying a later rollout was approved, calculating an unsupported duration, and saying browsing had been restored when it had remained available throughout an incident.

Input selection was also too positional: four samples from five sections could omit the main decision. Importance scoring and section coverage now work together, with evidence retained for all sections in the temporary workspace. The native model chat template replaces manually constructed formatting.

The larger candidate did not establish a reliable quality improvement. It generally used roughly 717 MiB model RSS and took longer; one run observed an approximately 813 MiB transient peak. It was not selected as the default. OS commit/address-space limits and sampled RSS monitoring are different protections: sampling can detect an overshoot after it occurs.

Historical measurements remain unchanged in the [experiment archive](archive/README.md). Their raw Korean and English outputs are evidence from synthetic fixtures, not application interface text or cached user summaries. Keyword overlap is not presented as semantic accuracy.

## Current guarantees and limits

The model can return only a valid candidate ID. The app checks provenance again and displays source text, never model-written wording. A malformed response falls back to a deterministically ranked source sentence. Whole candidates are removed to meet the input budget; sentences are never cropped or rewritten.

This protects source wording, numbers, names, dates, negation, and tense within the chosen sentence. It does not guarantee representative selection, document truth, or complete context. A product brief can yield an accurate sentence about section coverage while missing the overall product purpose. Spreadsheet wording is derived programmatically from structured cells and statistics.

The seven-case source check and unit tests validate this narrower contract. They do not establish general summary quality on complex documents. Real user-document evaluation and a complete 4 GB environment benchmark remain outstanding.
