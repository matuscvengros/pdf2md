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
--force-ocr       OCR entire pages instead of using the PDF's embedded text layer
--log-name NAME   Write logs/NAME-err.log and logs/NAME-output.log instead of the shared logs
--gpu             Force CUDA GPU
--cpu             Force CPU
```

### Running several books at once

Each CLI instance is a separate process, so the operating system can run different books on different CPU cores. The Markdown exporter itself is serial; starting Python threads within one instance does not parallelize it. Use one GPU converter alongside CPU math review as the default:

```bash
mkdir -p logs
./convert.sh input/a.pdf --gpu --ocr-language english --log-name a > logs/a-console.log &
free -m
nvidia-smi
```

If resources allow a second converter, give it a different PDF and `--log-name`. Without `--log-name`, every run truncates and writes the shared `logs/err.log` and `logs/output.log`, so a second run (even `--help`) wipes the first run's logs. Do not run two instances in batch mode over the same input directory; they would convert the same PDFs.

Each instance loads its own models and keeps its GPU memory until the process exits. On a 12 GB RTX 5070, scanned books of 450 to 760 pages peaked at 4 to 5 GB of GPU memory per instance. The GPU phase runs near 100% utilization, so two overlapping GPU phases share the GPU rather than finishing sooner. If overlapping conversion with another book's export, wait for `Finished converting document` in its output log, then check both RAM and free GPU memory before starting the next GPU process.

The same books peaked at about 15 GB of process memory, while a 600-page PDF with a text layer reached 28 GB, so page count alone does not predict memory. Use the `available` value from `free -m` (`MemAvailable`), and reserve at least the next process's expected peak plus several GB for the desktop and review workers. Two 28 GB conversions leave too little headroom on a 60 GB machine. Monitor available memory and swap during the run; wait for the current converter to exit if headroom is insufficient. `--cpu` selects CPU models but still retains the document in RAM.

### Device selection

With neither `--gpu` nor `--cpu`, Docling uses `device="auto"` and chooses CUDA for supported models when available. OCR can still use CPU depending on its backend. `--gpu` requires usable CUDA-enabled PyTorch and selects the PyTorch RapidOCR backend so OCR also uses CUDA. It fails explicitly if CUDA is unavailable. `--cpu` pins CPU. For this English scan, pass `--ocr-language english` to select the English OCR models.

Use `--force-ocr` when a damaged embedded text layer produces isolated characters or scrambled paragraphs. It replaces PDF-extracted text with full-page OCR; formula enrichment still runs. First check a few pages with `--page-start` and `--page-end`, since OCR can also misread valid text. Add `--force` when replacing an existing completed conversion.

### Logs

Errors and tracebacks go to `logs/err.log`; everything else (info/warning chatter from docling, rapidocr, transformers, tqdm) goes to `logs/output.log`. Both files are truncated at the start of each run. With `--log-name NAME` they are `logs/NAME-err.log` and `logs/NAME-output.log`. The output log records each section's physical page range in lines such as `section chapters/12-introduction.md pages 29-31`. If a degenerate element box would make a page crop smaller than one pixel, the converter renders the box clamped into the page instead of failing the PDF and logs a `page N: crop ... does not fit the page` warning. Completion records in `logs/converted-<hash>.log` persist between runs. The terminal only shows high-level status (`Converting ...`, `wrote ...`, `failed: ...`).

Docling's reading-order graph can omit blocks on some pages while reporting a successful conversion. The converter retains every block on an affected page group using Docling's geometric ordering and logs `reading-order fallback page N: recovered ...`. Check those physical pages against the PDF: their block order may need correction. Unaffected page groups keep Docling's original order. This adapter uses Docling's private `_predict_page` API and must be checked when its dependencies change.

Batch conversion continues after a failed PDF and exits with a nonzero status if any conversion failed.

## Math review

Formula recognition is unreliable on scans. [the Math section of AGENTS.md](AGENTS.md#math) describes how to check and correct every formula of a converted book against its PDF pages with the scripts in `math-review/`.
