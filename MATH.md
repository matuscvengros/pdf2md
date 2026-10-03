# Math review of converted books

`convert.py` produces readable section files, but its math is unreliable. This document describes how to check and correct every formula of a converted book against the PDF pages, using the scripts in `math-review/` and Claude Code workflows. The process works for any book; nothing in it depends on a particular title.

## Why the math needs a review

Docling recognizes display equations with a formula model and everything else with OCR. On a typewritten scan, the raw Markdown showed these failure modes:

- Lost or wrong subscripts and superscripts. A printed $N_x = 5 \cdot 10^6$, where $N_x$ stands for any subscripted quantity, arrives as `N = 5 10`, and $10^{-4}$ arrives as `10-*`.
- Dropped or doubled minus signs, including table columns where every value lost its sign.
- Garbage fused into formulas: figure axis labels, tick values and words from the neighbouring column.
- Equation numbers mangled into the LaTeX, for example `\quad ( 9 ) \quad _ { 4 } ^ { 5 }`.
- Displayed equations left as plain text, split into fragments, or missing.
- Inline math in prose flattened into plain text, with no `$...$` at all.
- About 10% of the display formulas Docling did produce are not valid LaTeX.

The converter can also drop whole blocks of text on some pages, when Docling's reading-order model logs `something went wrong`.

## The pattern

1. **Convert** the book with its own log name. The output log records each section's physical page range, which maps every section file back to its pages.
2. **Plan.** `math-review/plan.py` renders every page at 150 DPI, snapshots the section files before any edit, and groups consecutive sections into batches of at most 5 pages and 12 files. Each file belongs to exactly one batch, so no two agents edit the same file.
3. **Review.** `math-review/workflow.js` runs three stages per batch, pipelined so batches do not wait for each other:
   - **Fix**: one agent compares every formula on its pages with the Markdown and corrects the Markdown.
   - **Verify**: a fresh agent is told the fixer missed errors and introduced some. It re-checks everything, gets the fixer's change list as hints only, and fixes what remains.
   - **Recheck**: only if the verifier changed something, a third agent checks exactly those changes.
4. **Report.** `math-review/report.py` writes a summary, the full diff against the snapshot and a JSON list of every change.
5. **Audit.** `math-review/audit_sample.py` draws a random sample of formulas from the final Markdown. `math-review/audit.js` has read-only agents judge each one against the page. Because the sample is not limited to changed formulas, it measures the residual error rate.
6. **Fix audit findings**, then re-run the report.

### Rules the reviewers follow

- Display equations must match the print exactly: symbols, subscripts, superscripts, primes, accents, signs, digits, fractions and brackets. Printed equation numbers become `\tag{n}`. Agents add no tag where no number is printed, even if the text cites one.
- Equations that are missing, `<!-- formula-not-decoded -->` or garbled become `$$...$$` blocks in the right place.
- Inline math in prose, captions and table cells becomes `$...$`. Undecorated single-letter variables may stay plain text.
- Tables keep their structure. Only signs, exponents and symbols are corrected.
- Transcription only. A printed typo or an inconsistent symbol stays as printed.
- Nothing else changes: prose typos, headings, image links and paragraph order stay as they are. The exception is a dropped phrase that contains math, which is restored. Agents report missing non-math text instead of fixing it.
- Every formula is checked on a 300 DPI zoom (`math-review/crop_page.py`). Subscripts are not legible at 150 DPI.
- Every edited file must pass `math-review/check_math.js`, which parses each `$$...$$` and `$...$` with KaTeX.

## Running it

One-time setup, which installs KaTeX into `math-review/node_modules/`:

```bash
npm install --prefix math-review
```

Per book, with `<book>` as the PDF stem and `<name>` as a short log name:

```bash
./convert.sh input/<book>.pdf --gpu --ocr-language english --log-name <name> > logs/<name>-console.log
.venv/bin/python math-review/plan.py input/<book>.pdf logs/<name>-output.log --title "<Author>, <Title> (<Year>)"
```

`plan.py` writes `tmp/math-review/<book>/args.json`. In Claude Code, run the review workflow and pass that file's JSON content as the args object, not as a string:

```
Workflow({scriptPath: "math-review/workflow.js", args: <contents of tmp/math-review/<book>/args.json>})
```

To re-run only some batches, for example after an agent failure, add `"only": ["b012", "b047"]` to the args.

When the workflow finishes, report on it with the run's journal (`journal.jsonl` in the transcript directory the Workflow tool prints):

```bash
.venv/bin/python math-review/report.py <book> <transcript-dir>/journal.jsonl
```

This writes `logs/<book>-math-review.md`, `logs/<book>-math-review.diff` and `logs/<book>-math-review-changes.json`. Then audit a random sample, one mixed and one display-only:

```bash
.venv/bin/python math-review/audit_sample.py <book> --files 16 --per-file 12
.venv/bin/python math-review/audit_sample.py <book> --files 8 --per-file 10 --kind display --out audit-display
```

Run `math-review/audit.js` with each JSON file (or with their `groups` lists merged into one args object). Its final log line gives the verdict counts. Any formula judged `wrong` comes with the expected LaTeX. Fix those by hand, then re-run the report.

### Pilot first

Before a full run, pass `"only"` with a single batch of 5 math-dense pages. Read its diff against 300 DPI crops yourself. One batch takes about 9 minutes and shows whether the prompts suit the book's typography.

## Results from the first book

These numbers come from a 455-page scanned technical book with typewritten, hand-lettered equations, 266 section files and 113 batches.

| Measure | Before review | After review |
|---|---:|---:|
| Display formulas | 665 | 671 |
| Inline formulas | 0 | 4,642 |
| Formulas KaTeX cannot parse | 69 | 0 |
| Section files changed | | 200 of 266 |

The agents reported 3,458 changes: 3,314 by fixers, 144 by verifiers and none by rechecks. By kind there were 2,475 inline, 582 display, 217 restored phrases, 99 table cells, 48 equation numbers, 33 missing equations and 4 reverts of a fixer's wrong change. Reviewers also listed 480 unresolved notes. Most say an equation number is not printed, or that OCR dropped non-math prose.

The review used 271 agents (113 fix, 113 verify, 45 recheck) and took 48 minutes of wall-clock time at 16 concurrent agents. The agents used about 18.5 million tokens and 12,800 tool calls.

The audit sampled 245 formulas from 24 files across the book: 163 inline and 82 display. All 245 were judged correct, including three that looked wrong but match the print. With zero errors in $n$ samples, the 95% upper bound on the error rate is about $3/n$ (the rule of three, where $n$ is the number of audited formulas). That is about 1.2% for all formulas ($n = 245$) and 3.7% for display equations ($n = 82$). The audit took 24 agents, 2.3 minutes and about 0.9 million tokens.

## Limits and maintenance

- **Reconverting overwrites the review.** `--force` rewrites the section files. If the new export matches the old snapshot (`diff -r tmp/math-review/<book>/original output/<book>/chapters`), re-apply the review from the repository root with `patch -p0 < logs/<book>-math-review.diff`. Otherwise, run the review again.
- **Only math is in scope.** Prose OCR errors and text dropped by the reading-order model remain. Reviewers note them in the report's unresolved list. Anything starting with `MISSING BLOCK:` marks a block missing from the Markdown.
- **KaTeX checks syntax, not meaning.** A formula can parse and still be wrong. Only the visual comparison catches that, which is why the audit compares against the page rather than re-parsing.
- **Keep paths repository-relative.** `report.py` writes the diff with repository-relative paths so it applies on any checkout.
