# Writing reference raw layer

Build date: 2026-07-11

This directory contains page-level text/OCR and unreviewed candidate records derived from six external PDFs for private study.

- `manifest.json`: immutable source identity, path, page count, and SHA-256.
- `core/*/pages/`: page-by-page `pdftotext -layout` output for the three text-layer PDFs.
- `extracted/english_candidates.jsonl`: unreviewed English sentence/phrase line spans with source page and line.
- `extracted/headings.jsonl`: unreviewed heading hierarchy candidates.
- `extracted/topic_candidates.jsonl`: unreviewed bilingual topic-word candidates.
- `extracted/known_error_candidates.jsonl`: source errors explicitly rejected and corrected.
- `ocr/*/pages/`: English-only OCR for the historical prompt attachments.
- `ocr/prompt_candidates.jsonl`: 78 year/paper/page prompt candidates; Chinese visuals remain pending review.
- `print_asset_registry.json`: answer-sheet registration only.
- `reviewed/approved_patterns.jsonl`: manually reviewed sentence-pattern whitelist.
- `reviewed/approved_vocabulary.jsonl`: manually reviewed topic/collocation whitelist.

Nothing in this directory is approved for automatic promotion into the formal vocabulary or sentence-pattern banks.
