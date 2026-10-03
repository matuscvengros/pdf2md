# pdf2md

Convert PDFs to Markdown using [Docling](https://github.com/DS4SD/docling).

Requires [`uv`](https://github.com/astral-sh/uv) — it manages the virtualenv and dependencies automatically.

The GPU sample below was run with Python 3.12 and the locked dependencies. To install that environment:

```bash
uv sync --python 3.12 --locked
```

## Usage

Convert every PDF in `input/`:

```bash
./convert.sh
```

Convert a single PDF anywhere on disk:

```bash
./convert.sh path/to/file.pdf
```

Output contains section Markdown files directly in `output/<pdf-name>/chapters/` and their referenced images in `output/<pdf-name>/images/`. Files keep the original sequential prefix and heading slug, such as `01-introduction.md`. The script does not produce a combined book Markdown file.

The splitter keeps the original heading-based behavior. Each detected heading at `--split-level` starts a file that runs to the next heading at that level. The default is H1. OCR and heading detection determine these boundaries, so a book's title pages and subsections may also become separate files.

Successful exports record completion in `logs/converted-<hash>.log`. A later run skips that PDF only when the completion record and its chapter files still exist. Use `--force` to regenerate it.

### GPU page-range sample

Convert physical PDF pages 1 through 20 into heading-based section files:

```bash
./convert.sh input/book.pdf \
  --gpu --ocr-language english --page-start 1 --page-end 20
```

The sample directory is `output/book-pages-0001-0020/`. Its `chapters/` directory contains one file per detected H1 section. All files sit directly in that directory. Image paths are relative to each Markdown file.

These page numbers include the cover and front matter and may differ from printed book page numbers. Page ranges use Docling's `page_range` argument, so the remaining pages are not processed. Range output is separate from full-book output. Use `--force` to regenerate an existing sample and `--no-formulas` to skip formula enrichment for a faster run.

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
--split-level N   Heading level to split sections on (default: 1)
--page-start N    First physical PDF page, 1-based inclusive (default: 1)
--page-end N      Last physical PDF page, 1-based inclusive (default: final page)
--ocr-language L  Select english or chinese RapidOCR models
--log-name NAME   Write logs/NAME-err.log and logs/NAME-output.log instead of the shared logs
--gpu             Force CUDA GPU
--cpu             Force CPU
```

### Running several books at once

Run one instance per PDF, each with its own `--log-name`:

```bash
./convert.sh input/a.pdf --gpu --ocr-language english --log-name a > logs/a-console.log &
./convert.sh input/b.pdf --gpu --ocr-language english --log-name b > logs/b-console.log &
```

Without `--log-name`, every run truncates and writes the shared `logs/err.log` and `logs/output.log`, so a second run (even `--help`) wipes the first run's logs. Do not run two instances in batch mode over the same input directory; they would convert the same PDFs.

Each instance loads its own models and keeps its GPU memory until the process exits. On a 12 GB RTX 5070, scanned books of 450 to 760 pages peaked at 4 to 5 GB of GPU memory per instance. The GPU phase runs near 100% utilization, so two overlapping GPU phases share the GPU rather than finishing sooner. The same books peaked at about 15 GB of process memory, while a 600-page PDF with a text layer reached 28 GB, so page count alone does not predict memory. Check `free -m` before starting another instance.

### Device selection

With neither `--gpu` nor `--cpu`, Docling uses `device="auto"` and chooses CUDA for supported models when available. OCR can still use CPU depending on its backend. `--gpu` requires usable CUDA-enabled PyTorch and selects the PyTorch RapidOCR backend so OCR also uses CUDA. It fails explicitly if CUDA is unavailable. `--cpu` pins CPU. For this English scan, pass `--ocr-language english` to select the English OCR models.

### Logs

Errors and tracebacks go to `logs/err.log`; everything else (info/warning chatter from docling, rapidocr, transformers, tqdm) goes to `logs/output.log`. Both files are truncated at the start of each run. With `--log-name NAME` they are `logs/NAME-err.log` and `logs/NAME-output.log`. The output log records each section's physical page range in lines such as `section chapters/12-introduction.md pages 29-31`. Completion records in `logs/converted-<hash>.log` persist between runs. The terminal only shows high-level status (`Converting ...`, `wrote ...`, `failed: ...`).

Batch conversion continues after a failed PDF and exits with a nonzero status if any conversion failed.
