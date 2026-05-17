# pdf2md

Convert PDFs to Markdown using [Docling](https://github.com/DS4SD/docling).

## Usage

Convert everything in `input/`:

```bash
./convert.sh
```

Convert a single PDF anywhere on disk:

```bash
./convert.sh path/to/file.pdf
```

Output goes to `output/<pdf-name>/<pdf-name>.md` with images in `output/<pdf-name>/images/`. The document is also split into per-chapter files under `output/<pdf-name>/chapters/` based on top-level headings.

Requires [`uv`](https://github.com/astral-sh/uv) — it manages the virtualenv and dependencies automatically. Already-converted PDFs are skipped — pass `--force` to reconvert.

### Options

```
--output DIR     Output directory (default: output)
--input DIR      Input directory when no file is given (default: input)
--scale FLOAT    Image scale factor (default: 2.0)
--no-formulas    Disable formula enrichment (faster)
--force          Reconvert PDFs even if output exists
--no-split       Skip splitting into per-chapter files
--split-level N  Heading level to split on (default: 1)
```
