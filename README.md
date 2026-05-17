# pdf2md

Convert PDFs to Markdown using [Docling](https://github.com/DS4SD/docling).

Requires [`uv`](https://github.com/astral-sh/uv) — it manages the virtualenv and dependencies automatically.

## Usage

Convert every PDF in `input/`:

```bash
./convert.sh
```

Convert a single PDF anywhere on disk:

```bash
./convert.sh path/to/file.pdf
```

Output goes to `output/<pdf-name>/<pdf-name>.md`, with images in `output/<pdf-name>/images/` and per-chapter files (split on top-level headings) in `output/<pdf-name>/chapters/`. Already-converted PDFs are skipped unless `--force` is passed.

### Arguments

```
file             Single PDF to convert. If omitted, processes every PDF in --input.
```

### Options

```
--input DIR       Input directory when no file is given (default: input)
--output DIR      Output directory (default: output)
--scale FLOAT     Image scale factor (default: 2.0)
--no-formulas     Disable formula enrichment (faster)
--force           Reconvert PDFs even if output exists
--no-split        Skip splitting into per-chapter files
--split-level N   Heading level to split chapters on (default: 1)
--gpu             Run model inference on CUDA GPU instead of CPU
```
