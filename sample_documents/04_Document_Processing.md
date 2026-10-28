# Document processing principles

## Local processing

Browsing, search, preview, and lightweight sentence selection run on this computer. File content and paths are not sent to a server. Routine use requires no internet connection or account.

## Explorer performance first

Browsing and search have the highest priority. Previews have fixed limits, and document parsers run in separate processes. The explorer remains usable if a parser exits.

## Documents only

An extension alone does not enable summaries. The app checks actual signatures and container structure, then validates the parser output. Text containing code or machine logs is excluded.

## Preserve sources and numbers

File names, actual types, and full paths appear before summaries. Selected original sentences retain their wording and page, paragraph, slide, or sheet location.

## Changed files and temporary state

Summary and extraction results are not cached. Every request rereads the source. Temporary evidence is deleted when changing files, cancelling a job, or closing the app normally. Changes during processing cause the result to be discarded.
