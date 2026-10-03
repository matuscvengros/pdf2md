"""Prepare the math review of one converted book.

Reads the section page map that convert.py logs ("section chapters/<file> pages
A-B"), renders every PDF page to a 150 DPI overview PNG, snapshots the section
files before any edit, groups the sections into page batches and writes the
Workflow args for math-review/workflow.js.

Usage: .venv/bin/python math-review/plan.py PDF OUTPUT_LOG --title "Author, Title (Year)"

Writes under tmp/: pages/<stem>/p-*.png, math-review/<stem>/original/ (only if
it does not exist yet) and math-review/<stem>/args.json.
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser()
parser.add_argument("pdf", type=Path)
parser.add_argument("log", type=Path, help="convert.py output log of the run, e.g. logs/NAME-output.log")
parser.add_argument("--title", help="Book title used in reviewer prompts (default: PDF stem)")
parser.add_argument("--max-pages", type=int, default=5, help="Page span per batch (default: 5)")
parser.add_argument("--max-files", type=int, default=12, help="Section files per batch (default: 12)")
args = parser.parse_args()

pdf = args.pdf.resolve()
stem = pdf.stem
chapters = ROOT / "output" / stem / "chapters"
pages_dir = ROOT / "tmp" / "pages" / stem
work = ROOT / "tmp" / "math-review" / stem
page_count = len(pdfium.PdfDocument(str(pdf)))

# Overview renders. pdftoppm pads page numbers to the digit count of the last page.
pages_dir.mkdir(parents=True, exist_ok=True)
if len(list(pages_dir.glob("p-*.png"))) != page_count:
    chunk = -(-page_count // 8)
    procs = [
        subprocess.Popen(["pdftoppm", "-r", "150", "-png", "-f", str(s), "-l", str(min(s + chunk - 1, page_count)), str(pdf), str(pages_dir / "p")])
        for s in range(1, page_count + 1, chunk)
    ]
    if any(p.wait() for p in procs):
        raise SystemExit("pdftoppm failed")
page_files = {int(m.group(1)): m.group(1) for p in pages_dir.glob("p-*.png") if (m := re.fullmatch(r"p-(\d+)\.png", p.name))}
if sorted(page_files) != list(range(1, page_count + 1)):
    raise SystemExit(f"expected {page_count} page renders in {pages_dir}")
pad = len(next(iter(page_files.values())))

sections = []
for m in re.finditer(r"section chapters/(\S+\.md) pages (\S+)-(\S+)", args.log.read_text(encoding="utf-8")):
    name, first, last = m.groups()
    prev_last = sections[-1][2] if sections else 1
    first = int(first) if first != "?" else prev_last
    last = int(last) if last != "?" else first
    sections.append([name, first, last])
on_disk = sorted(p.name for p in chapters.glob("*.md"))
if not on_disk:
    raise SystemExit(f"no section files in {chapters}; convert the book first")
if sorted(s[0] for s in sections) != on_disk:
    raise SystemExit(f"{args.log} lists {len(sections)} sections but {chapters} has {len(on_disk)} files; use the log of the run that wrote them")

if work.joinpath("original").exists():
    print(f"keeping existing snapshot {work / 'original'}")
else:
    work.mkdir(parents=True, exist_ok=True)
    shutil.copytree(chapters, work / "original")

batches, current = [], []
for s in sections:
    if current:
        first = min(c[1] for c in current + [s])
        last = max(c[2] for c in current + [s])
        if last - first + 1 > args.max_pages or len(current) >= args.max_files:
            batches.append(current)
            current = []
    current.append(s)
if current:
    batches.append(current)

workflow_args = {
    "root": str(ROOT),
    "title": args.title or stem,
    "pdf": str(pdf),
    "chapters": str(chapters),
    "pages": str(pages_dir),
    "pagePad": pad,
    "batches": [
        {"id": f"b{i:03d}", "first": min(s[1] for s in group), "last": max(s[2] for s in group), "sections": group}
        for i, group in enumerate(batches, 1)
    ],
}
out = work / "args.json"
out.write_text(json.dumps(workflow_args, separators=(",", ":")))
covered = {p for b in workflow_args["batches"] for p in range(b["first"], b["last"] + 1)}
print(f"{len(sections)} sections in {len(batches)} batches; pages without a section: {sorted(set(range(1, page_count + 1)) - covered) or 'none'}")
print(f"workflow args: {out}")
