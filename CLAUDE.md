# pdf2md

Single-script tool that converts PDFs to Markdown via Docling. Output contains heading-based section files directly in `output/<name>/chapters/` and referenced images in `output/<name>/images/`. Keep the original sequential prefix and heading-slug filenames, such as `01-introduction.md`. Do not produce combined book Markdown or create nested chapter directories.

## Layout

- `convert.sh` — thin entry point that `exec`s `uv run convert.py "$@"`. `uv` handles venv + dependency sync.
- `convert.py` — the tool itself. `build_converter` / `convert_one` / `split_into_chapters` / `main`.
- `input/`, `output/` — tracked dirs with `.gitkeep`.
- `math-review/` and the Math section of `AGENTS.md` — tooling and instructions for checking a converted book's math against the PDF with Claude Code workflows. After converting a book, review its math as the Math section below describes. Keep these files book-agnostic: the repository is public, so no titles, file stems or local paths.
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
- Record successful exports and section page ranges in a persistent `logs/converted-<hash>.log` completion record. Skip only when that record and its chapter files exist, unless `--force`. Page ranges are comment lines, so older path-only records remain valid for skipping.
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

## Math

**Important: Math review is required whenever the source contains math.** After converting, check every section containing display equations, inline expressions, mathematical table cells, or captions against the source PDF. Run independent page batches in parallel. Each batch must have a fixer, a fresh adversarial verifier instructed to expect missed or introduced errors, and a third reviewer for verifier edits. KaTeX syntax checks alone do not establish transcription accuracy. Report incomplete coverage and unreadable source expressions explicitly.

Use the current Codex agent and independent Codex agents for math review. **Do not start Claude CLI, Claude workflows, or use a Claude account.** The Claude-specific commands below are legacy documentation, not authorization to execute them.

`convert.py` produces readable section files, but its math is unreliable. This document describes how to check and correct every formula of a converted book against the PDF pages, using the scripts in `math-review/` and Claude Code workflows. The process works for any book; nothing in it depends on a particular title.

### Why the math needs a review

Docling recognizes display equations with a formula model and everything else with OCR. On a typewritten scan, the raw Markdown showed these failure modes:

- Lost or wrong subscripts and superscripts. A printed $N_x = 5 \cdot 10^6$, where $N_x$ stands for any subscripted quantity, arrives as `N = 5 10`, and $10^{-4}$ arrives as `10-*`.
- Dropped or doubled minus signs, including table columns where every value lost its sign.
- Garbage fused into formulas: figure axis labels, tick values and words from the neighbouring column.
- Equation numbers mangled into the LaTeX, for example `\quad ( 9 ) \quad _ { 4 } ^ { 5 }`.
- Displayed equations left as plain text, split into fragments, or missing.
- Inline math in prose flattened into plain text, with no `$...$` at all.
- About 10% of the display formulas Docling did produce are not valid LaTeX.

The converter can also drop whole blocks of text on some pages, when Docling's reading-order model logs `something went wrong`.

### The pattern

1. **Convert** the book with its own log name. The output log and persistent completion record retain each section's physical page range, which maps every section file back to its pages.
2. **Plan.** `math-review/plan.py` renders every page at 150 DPI, snapshots the section files before any edit, and groups consecutive sections into batches of at most 5 pages and 12 files. A single section spanning more than 5 pages stays in one batch. Each file belongs to exactly one batch, so no two agents edit the same file.
3. **Review.** `math-review/workflow.js` runs three stages per batch, pipelined so batches do not wait for each other:
   - **Fix**: one agent compares every formula on its pages with the Markdown and corrects the Markdown.
   - **Verify**: a fresh agent is told the fixer missed errors and introduced some. It re-checks everything, gets the fixer's change list as hints only, and fixes what remains.
   - **Recheck**: only if the verifier changed something, a third agent checks exactly those changes.
4. **Report.** `math-review/report.py` writes a summary, the full diff against the snapshot and a JSON list of every change.
5. **Audit.** `math-review/audit_sample.py` draws a random sample of formulas from the final Markdown. `math-review/audit.js` has read-only agents judge each one against the page. Because the sample is not limited to changed formulas, it measures the residual error rate.
6. **Fix audit findings**, then re-run the report.

#### Rules the reviewers follow

- Display equations must match the print exactly: symbols, subscripts, superscripts, primes, accents, signs, digits, fractions and brackets. Printed equation numbers become `\tag{n}`. Agents add no tag where no number is printed, even if the text cites one.
- Equations that are missing, `<!-- formula-not-decoded -->` or garbled become `$$...$$` blocks in the right place.
- Inline math in prose, captions and table cells becomes `$...$`. Undecorated single-letter variables may stay plain text.
- Tables keep their structure. Only signs, exponents and symbols are corrected.
- Transcription only. A printed typo or an inconsistent symbol stays as printed.
- Nothing else changes: prose typos, headings, image links and paragraph order stay as they are. The exception is a dropped phrase that contains math, which is restored. Agents report missing non-math text instead of fixing it.
- Use surrounding context or token boundaries for replacements. Inspect the diff for math inserted inside ordinary words or proper names, and restore any accidental prose edits before finishing. Verifiers also check the surrounding prose of each correction.
- Before restoring missing math, search neighbouring section files read-only. Reading-order errors can place it under a later heading; report that location rather than adding a duplicate or editing another agent's file.
- Every formula is checked on a 300 DPI zoom (`math-review/crop_page.py`). Subscripts are not legible at 150 DPI.
- Every edited file must pass `math-review/check_math.js`, which parses each `$$...$$` and `$...$` with KaTeX.

### Running it

One-time setup, which installs KaTeX into `math-review/node_modules/`:

```bash
npm install --prefix math-review
```

Per book, with `<book>` as the PDF stem and `<name>` as a short log name:

```bash
./convert.sh input/<book>.pdf --gpu --ocr-language english --log-name <name> > logs/<name>-console.log
.venv/bin/python math-review/plan.py input/<book>.pdf logs/<name>-output.log --title "<Author>, <Title> (<Year>)"
```

If the output log has been overwritten, pass the matching `logs/converted-<hash>.log` to `plan.py` instead. New completion records preserve the source page map; older path-only records require the original output log.

`plan.py` writes `tmp/math-review/<book>/args.json`. In Claude Code, run the review workflow and pass that file's JSON content as the args object, not as a string:

```
Workflow({scriptPath: "math-review/workflow.js", args: <contents of tmp/math-review/<book>/args.json>})
```

With an authenticated local Claude Code CLI that exposes the Workflow tool, the same workflow can be started from a terminal:

```bash
.venv/bin/python math-review/run.py tmp/math-review/<book>/args.json --log-name <name>-math
```

The runner keeps the CLI's default model and saves its stream and errors in `logs/<name>-math-workflow.jsonl` and `logs/<name>-math-workflow-err.log`. Its CLI exit status does not certify review completion; check the workflow journal with `report.py` below. Use a distinct log name for each parallel run.

To re-run only some batches, for example after an agent failure, add `"only": ["b012", "b047"]` to the args.

To continue an interrupted review without repeating completed stages, pass its journals in chronological order:

```bash
.venv/bin/python math-review/run.py tmp/math-review/<book>/args.json --log-name <name>-resume --resume-journals <first-journal> <later-journal>
```

The runner validates the results and reuses only current successful stages. A new fixer invalidates previous verification; a new verifier invalidates its recheck. Use this only while the exported files still correspond to the journals: reconversion or unrecorded edits require a fresh review. Include both the earlier journals and the new journal when reporting the resumed run.

When the workflow finishes, report on it with the run's journal (`journal.jsonl` in the transcript directory the Workflow tool prints):

```bash
.venv/bin/python math-review/report.py <book> <transcript-dir>/journal.jsonl
```

For a pilot followed by a full run or retries, pass all journal paths in chronological order. A later fixer invalidates earlier verification for that batch, and a later verifier invalidates its earlier recheck. The report exits with status 1 if any required stage is missing, malformed, or fails its KaTeX check, or if the planned files differ from the export or snapshot. An incomplete run must not be reported as a finished review.

This writes `logs/<book>-math-review.md`, `logs/<book>-math-review.diff` and `logs/<book>-math-review-changes.json`. Then audit a random sample, one mixed and one display-only:

```bash
.venv/bin/python math-review/audit_sample.py <book> --files 16 --per-file 12
.venv/bin/python math-review/audit_sample.py <book> --files 8 --per-file 10 --kind display --out audit-display
```

Run `math-review/audit.js` with each JSON file (or with their `groups` lists merged into one args object). Its final log line gives the verdict counts. Any formula judged `wrong` comes with the expected LaTeX. Fix those by hand, then re-run the report.

The terminal runner also supports audit args: `.venv/bin/python math-review/run.py tmp/math-review/<book>/audit-args.json --kind audit --log-name <name>-audit`.

The audit requires exactly one verdict per sampled formula. Missing or duplicate verdicts fail the audit. Formulas marked `unclear` or `not-found` remain unresolved and cannot be counted as correct.

#### Pilot first

Before a full run, pass `"only"` with a single batch of 5 math-dense pages. Read its diff against 300 DPI crops yourself. One batch takes about 9 minutes and shows whether the prompts suit the book's typography.

### Results from the first book

These numbers come from a 455-page scanned technical book with typewritten, hand-lettered equations, 266 section files and 113 batches.

| Measure | Before review | After review |
|---|---:|---:|
| Display formulas | 665 | 671 |
| Inline formulas | 0 | 4,642 |
| Formulas KaTeX cannot parse | 69 | 0 |
| Section files changed | | 200 of 266 |

The agents reported 3,458 changes: 3,314 by fixers, 144 by verifiers and none by rechecks. By kind there were 2,475 inline, 582 display, 217 restored phrases, 99 table cells, 48 equation numbers, 33 missing equations and 4 reverts of a fixer's wrong change. Reviewers also listed 480 unresolved notes. Most say an equation number is not printed, or that OCR dropped non-math prose.

The review used 271 agents (113 fix, 113 verify, 45 recheck) and took 48 minutes of wall-clock time at 16 concurrent agents. The agents used about 18.5 million tokens and 12,800 tool calls.

The audit sampled 245 formulas from 24 files across the book: 163 inline and 82 display. All 245 were judged correct, including three that looked wrong but match the print. For independent random formula samples, zero errors gives a rough 95% upper bound of $3/n$: about 1.2% for 245 formulas and 3.7% for 82 display equations. This audit samples clusters within weighted section files, so those figures are benchmarks, not valid confidence bounds for its residual error rate. It also cannot detect equations omitted from the Markdown. The full visual review must check those. The audit took 24 agents, 2.3 minutes and about 0.9 million tokens.

### Limits and maintenance

- **Reconverting overwrites the review.** `--force` rewrites the section files. If the new export matches the old snapshot (`diff -r tmp/math-review/<book>/original output/<book>/chapters`), re-apply the review from the repository root with `patch -p0 < logs/<book>-math-review.diff`. Otherwise, run the review again.
- **Only math is in scope.** Prose OCR errors and text dropped by the reading-order model remain. Reviewers note them in the report's unresolved list. Anything starting with `MISSING BLOCK:` marks a block missing from the Markdown.
- **KaTeX checks syntax, not meaning.** A formula can parse and still be wrong. Only the visual comparison catches that, which is why the audit compares against the page rather than re-parsing.
- **Keep paths repository-relative.** `report.py` writes the diff with repository-relative paths so it applies on any checkout.
