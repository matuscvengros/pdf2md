# pdf2md

Single-script tool that converts PDFs to Markdown via Docling. Output contains heading-based section files directly in `output/<name>/chapters/` and referenced images in `output/<name>/images/`. Keep the original sequential prefix and heading-slug filenames, such as `01-introduction.md`. Do not produce combined book Markdown or create nested chapter directories.

## Layout

- `convert.sh` — thin entry point that `exec`s `uv run convert.py "$@"`. `uv` handles venv + dependency sync.
- `convert.py` — the tool itself. `build_converter` / `convert_one` / `split_into_chapters` / `main`.
- `input/`, `output/` — tracked dirs with `.gitkeep`.
- `math-review/` and `MATH.md` — tooling and instructions for checking a converted book's math against the PDF with Claude Code workflows. After converting a book, review its math as `MATH.md` describes. Keep these files book-agnostic: the repository is public, so no titles, file stems or local paths.
- `pyproject.toml` — pins `docling>=2.0,<3` (docling APIs evolve; a major bump can break us).

## CLI shape

- No positional arg → process every `*.pdf` in `--input` (default `input/`).
- One positional arg → that single PDF file (any path on disk).
- More than one positional arg → not supported. If asked for multi-file, add a `nargs="+"` change consciously rather than auto-extending.
- `--page-start` and `--page-end` select physical PDF pages, with 1-based inclusive bounds. Partial conversions use a separate output directory.
- `--split-level` selects the heading level for section splitting, default H1. Do not add combined book Markdown, JSON, or page-chunk exports.

## Conventions

- Python 3.10+, `pathlib` everywhere, no `os.path`.
- Users run `./convert.sh`, not `python convert.py` directly — the wrapper delegates to `uv run`.
- Batch must not abort on a single bad PDF — per-file `try/except` in `main`.
- Record successful exports in a persistent `logs/converted-<hash>.log` completion record. Skip only when that record and its chapter files exist, unless `--force`.
- New behavior knobs go through `argparse`, not module constants.
- Device selection: `--gpu`/`--cpu` are mutually exclusive and *both* opt-in. With neither, we don't set `accelerator_options` and Docling runs `device="auto"`, which **picks CUDA when a working NVIDIA GPU is present** — i.e. the absence of `--gpu` is not the same as CPU-only. Use `--cpu` to actually pin CPU. Don't change this default to CPU without a reason; auto matches Docling's own behavior.
- Logs: `convert.py` redirects all Python logging and stderr into `logs/`. Errors (ERROR level + the per-PDF traceback we emit) land in `logs/err.log`; everything else (INFO/WARNING from docling/rapidocr/transformers, tqdm bars, raw stderr writes) lands in `logs/output.log`. Both files are truncated at the start of each run, even for `--help`. Concurrent runs must each pass a distinct `--log-name NAME`, which switches them to `logs/NAME-err.log` and `logs/NAME-output.log`. The output log records each section's page range (`section chapters/<file> pages A-B`). The terminal only sees `print()` from `convert.py`. Don't add new noisy `print()`s; if you need to log, use `logging`.

## Non-goals

- No tests (small script, not worth it).
- No fancy logging — `print` is fine.
- Don't add abstractions for hypothetical multi-format support; this is PDF-only.
- Preserve the original heading-based `split_into_chapters` algorithm. It walks `DoclingDocument.iterate_items()` and serializes each section with `from_element`/`to_element`. It does `save_as_markdown`'s picture step (`_with_pictures_refs`) once, then calls `export_to_markdown` per section on that copy. Calling `save_as_markdown` per section produces identical files, but it deep-copies the document and re-saves every picture on each call, which made a 700-page export take 1-2 hours. Boundaries are `SectionHeaderItem` at `--split-level`. Do not add chapter-number detection or group subsections into larger chapters. Don't fall back to regex on rendered Markdown; use the parsed tree.
- `SafeCropDocumentBackend` is Docling's default PDF backend with one change: a page crop that pypdfium2 rejects as smaller than one pixel is clamped into the page and logged as a warning instead of failing the whole PDF. Its `load_page` copies `DoclingParseDocumentBackend.load_page` (`docling/backend/docling_parse_backend.py`) and must stay in sync with it when docling is upgraded.
- The iteration args in `split_into_chapters` (`with_groups=True`, `traverse_pictures=True`, `included_content_layers={BODY}`) must stay in sync with docling's markdown serializer (`docling_core/transforms/serializer/common.py::_iterate_items`). Otherwise the indices we pass as `from_element`/`to_element` won't line up with the serializer's body slicing — chapters will silently contain wrong content.

## Temporary files and logs

- Put all temporary files created during any task in the repository's `tmp/` directory.
- Put all log files created during any task in the repository's `logs/` directory.
- Keep `tmp/` and `logs/` in `.gitignore`, and never commit their contents.
