# pdf2md

Single-script tool that converts PDFs to Markdown via Docling. Output: `output/<name>/<name>.md`, per-chapter files in `output/<name>/chapters/`, and referenced images in `output/<name>/images/`.

## Layout

- `convert.sh` — thin entry point that `exec`s `uv run convert.py "$@"`. `uv` handles venv + dependency sync.
- `convert.py` — the tool itself. `build_converter` / `convert_one` / `split_into_chapters` / `main`.
- `input/`, `output/` — tracked dirs with `.gitkeep`.
- `pyproject.toml` — pins `docling>=2.0,<3` (docling APIs evolve; a major bump can break us).

## CLI shape

- No positional arg → process every `*.pdf` in `--input` (default `input/`).
- One positional arg → that single PDF file (any path on disk).
- More than one positional arg → not supported. If asked for multi-file, add a `nargs="+"` change consciously rather than auto-extending.

## Conventions

- Python 3.10+, `pathlib` everywhere, no `os.path`.
- Users run `./convert.sh`, not `python convert.py` directly — the wrapper delegates to `uv run`.
- Batch must not abort on a single bad PDF — per-file `try/except` in `main`.
- Skip files where `output/<name>/<name>.md` already exists unless `--force`.
- New behavior knobs go through `argparse`, not module constants.

## Non-goals

- No tests (small script, not worth it).
- No fancy logging — `print` is fine.
- Don't add abstractions for hypothetical multi-format support; this is PDF-only.
- Chapter splitting walks `DoclingDocument.iterate_items()` and re-invokes `save_as_markdown(from_element=..., to_element=...)` per section. Boundaries are `SectionHeaderItem` at `--split-level`. Don't fall back to regex on the rendered Markdown — we have the parsed tree, use it.
- The iteration args in `split_into_chapters` (`with_groups=True`, `traverse_pictures=True`, `included_content_layers={BODY}`) must stay in sync with docling's markdown serializer (`docling_core/transforms/serializer/common.py::_iterate_items`). Otherwise the indices we pass as `from_element`/`to_element` won't line up with the serializer's body slicing — chapters will silently contain wrong content.
