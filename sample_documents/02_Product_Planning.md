# Product planning meeting

## Background

The document explorer planning meeting took place on October 26, 2026. The goal was to decide the initial browsing and search experience.

## User needs

Users should find documents by folder location and words in the content even when they cannot remember a filename. The actual file type and full path should appear before reading a summary.

## Main decision

The first release will prioritize file browsing, filename search, content search, and document previews. The default summary will select original source text without a network connection.

## Performance criteria

The compatibility target is a computer with 4 GB of RAM or less. Only one document parser runs at a time. Previews are limited to 24,000 characters. Each file-list page displays at most 160 items.

## Next steps

Large documents and spoofed file formats will be checked by November 2, 2026. Compatibility will be confirmed after measurements in an actual 4 GB environment.
