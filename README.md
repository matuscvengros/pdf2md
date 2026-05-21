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
--gpu             Force CUDA GPU
--cpu             Force CPU
```

### Device selection

With neither `--gpu` nor `--cpu`, Docling runs on `device="auto"`: it picks **CUDA when a working NVIDIA GPU is present** and falls back to CPU otherwise. So on a GPU box, plain `./convert.sh` will use the GPU even though there's no `--gpu` flag — this is Docling's default, not a bug. Pass `--cpu` to actually pin CPU (e.g. when `auto` is picking up a wedged GPU).

### Logs

Errors and tracebacks go to `logs/err.log`; everything else (info/warning chatter from docling, rapidocr, transformers, tqdm) goes to `logs/output.log`. Both files are truncated at the start of each run. The terminal only shows high-level status (`Converting ...`, `wrote ...`, `failed: ...`).
