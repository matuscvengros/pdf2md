"""Summarize a math-review workflow run for one book.

Usage: .venv/bin/python math-review/report.py BOOK_STEM JOURNAL_JSONL

JOURNAL_JSONL is the journal.jsonl in the workflow run's transcript directory.
Batches come from tmp/math-review/<BOOK_STEM>/args.json (written by plan.py).

Writes:
  logs/<BOOK_STEM>-math-review.md            summary, per-batch counts, unresolved items
  logs/<BOOK_STEM>-math-review-changes.json  every reported change, by batch and stage
  logs/<BOOK_STEM>-math-review.diff          diff of the snapshot in tmp/math-review/<BOOK_STEM>/original
                                             against output/<BOOK_STEM>/chapters
"""
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
stem, journal = sys.argv[1], Path(sys.argv[2])
chapters = ROOT / "output" / stem / "chapters"
original = ROOT / "tmp" / "math-review" / stem / "original"
batches = {b["id"]: b for b in json.loads((ROOT / "tmp" / "math-review" / stem / "args.json").read_text())["batches"]}

labels, results = {}, {}
for line in journal.read_text().splitlines():
    rec = json.loads(line)
    if rec.get("type") == "started":
        labels[rec["key"]] = rec["label"]
    elif rec.get("type") == "result":
        results[rec["key"]] = rec.get("result")

by_batch = collections.defaultdict(dict)
for key, label in labels.items():
    m = re.match(r"(fix|verify|recheck):(b\d+)", label)
    if m:
        by_batch[m.group(2)][m.group(1)] = results.get(key, "MISSING")

kinds = collections.Counter()
stage_changes = collections.Counter()
unresolved, failed, rows, all_changes = [], [], [], []
for bid in sorted(batches):
    b, stages = batches[bid], by_batch.get(bid, {})
    row = [bid, f"{b['first']}-{b['last']}", str(len(b["sections"]))]
    for stage in ("fix", "verify", "recheck"):
        r = stages.get(stage)
        if r is None and stage == "recheck":
            row.append("-")
            continue
        if not isinstance(r, dict):
            failed.append(f"{bid} {stage}: {'not run' if r is None else r}")
            row.append("FAILED")
            continue
        row.append(str(len(r["changes"])))
        stage_changes[stage] += len(r["changes"])
        for c in r["changes"]:
            kinds[c["kind"]] += 1
            all_changes.append({"batch": bid, "stage": stage, **c})
        for u in r["unresolved"]:
            unresolved.append(f"- {bid} {stage}, {u['file']} p{u['page']}: {u['issue']}")
        if not r["katex_clean"]:
            failed.append(f"{bid} {stage}: reported KaTeX not clean")
    rows.append(row)

files = sorted(chapters.glob("*.md"))
katex = subprocess.run(["node", str(ROOT / "math-review/check_math.js"), *map(str, files)], capture_output=True, text=True)
katex_before = subprocess.run(["node", str(ROOT / "math-review/check_math.js"), *map(str, sorted(original.glob("*.md")))], capture_output=True, text=True)
# Repository-relative paths, so `patch -p0` from the repository root re-applies the review.
diff = subprocess.run(["diff", "-ru", str(original.relative_to(ROOT)), str(chapters.relative_to(ROOT))], cwd=ROOT, capture_output=True, text=True).stdout
(ROOT / "logs" / f"{stem}-math-review.diff").write_text(diff)
(ROOT / "logs" / f"{stem}-math-review-changes.json").write_text(json.dumps(all_changes, indent=1, ensure_ascii=False))
changed_files = sorted({line[4:].split("\t")[0] for line in diff.splitlines() if line.startswith("+++ ")})


def count(src: str) -> tuple[int, int]:
    display = len(re.findall(r"\$\$[\s\S]+?\$\$", src))
    inline = len(re.findall(r"(?<![\\$])\$(?!\$)[^$\n]+?(?<!\\)\$", re.sub(r"\$\$[\s\S]+?\$\$", "", src)))
    return display, inline


before = [count(p.read_text(encoding="utf-8")) for p in original.glob("*.md")]
after = [count(p.read_text(encoding="utf-8")) for p in files]
report = [
    f"# Math review: {stem}",
    "",
    f"Batches: {len(batches)}. Section files: {len(files)}, of which {len(changed_files)} changed.",
    f"Display formulas: {sum(d for d, _ in before)} before, {sum(d for d, _ in after)} after. "
    f"Inline formulas: {sum(i for _, i in before)} before, {sum(i for _, i in after)} after.",
    f"KaTeX before: {katex_before.stdout.strip().splitlines()[-1]}. KaTeX after: {katex.stdout.strip().splitlines()[-1]}.",
    f"Reported changes: fix {stage_changes['fix']}, verify {stage_changes['verify']}, recheck {stage_changes['recheck']}.",
    "Changes by kind: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common()) + ".",
    "",
    f"Full diff: logs/{stem}-math-review.diff. Change list: logs/{stem}-math-review-changes.json. "
    f"Pre-review snapshot: tmp/math-review/{stem}/original/.",
    "",
    "## Failures",
    "",
    *(f"- {f}" for f in failed),
    *([] if failed else ["None."]),
    "",
    "## KaTeX problems after review",
    "",
    "```",
    katex.stdout.strip(),
    "```",
    "",
    "## Per batch (changes reported per stage)",
    "",
    "| Batch | Pages | Files | Fix | Verify | Recheck |",
    "|---|---|---:|---:|---:|---:|",
    *(f"| {' | '.join(r)} |" for r in rows),
    "",
    "## Unresolved items reported by reviewers",
    "",
    *unresolved,
    *([] if unresolved else ["None."]),
    "",
]
(ROOT / "logs" / f"{stem}-math-review.md").write_text("\n".join(report))
print("\n".join(report[:12]))
