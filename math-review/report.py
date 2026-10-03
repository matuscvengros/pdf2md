"""Summarize a math-review workflow run for one book.

Usage: .venv/bin/python math-review/report.py BOOK_STEM JOURNAL_JSONL [JOURNAL_JSONL ...]

JOURNAL_JSONL is the journal.jsonl in the workflow run's transcript directory.
Pass rerun journals oldest first. A newer stage invalidates its earlier checks.
Batches come from tmp/math-review/<BOOK_STEM>/args.json (written by plan.py).
Exits 1 if required stages, file coverage or the final KaTeX check are incomplete.

Writes:
  logs/<BOOK_STEM>-math-review.md            summary, per-batch counts, unresolved items
  logs/<BOOK_STEM>-math-review-changes.json  every reported change, by batch and stage
  logs/<BOOK_STEM>-math-review.diff          diff of the snapshot in tmp/math-review/<BOOK_STEM>/original
                                             against output/<BOOK_STEM>/chapters
"""
import argparse
import collections
import json
import re
import subprocess
import sys
from pathlib import Path

from journal import read_stages, valid_result as owned_result

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("stem")
parser.add_argument("journals", nargs="+", type=Path, help="Workflow journals, oldest first; later stages supersede earlier attempts")
args = parser.parse_args()
stem = args.stem
chapters = ROOT / "output" / stem / "chapters"
original = ROOT / "tmp" / "math-review" / stem / "original"
planned = json.loads((ROOT / "tmp" / "math-review" / stem / "args.json").read_text())["batches"]
batches = {b["id"]: b for b in planned}
failed = []
if len(batches) != len(planned):
    failed.append("duplicate batch IDs in plan")
planned_names = [s[0] for b in planned for s in b["sections"]]
if len(set(planned_names)) != len(planned_names):
    failed.append("a section is assigned to more than one batch")
for label, directory in (("export", chapters), ("snapshot", original)):
    names = sorted(p.name for p in directory.glob("*.md"))
    if names != sorted(planned_names):
        failed.append(f"{label} files do not match the plan: missing {sorted(set(planned_names) - set(names))}, extra {sorted(set(names) - set(planned_names))}")
if not batches:
    failed.append("the plan contains no batches")

by_batch, attempts, journal_errors = read_stages(args.journals, batches)
failed.extend(journal_errors)


def valid_result(result, batch):
    return owned_result(result, batch, ROOT, chapters)

kinds = collections.Counter()
stage_changes = collections.Counter()
unresolved, rows, all_changes = [], [], []
for bid, stage, result in attempts:
    if valid_result(result, batches[bid]):
        stage_changes[stage] += len(result["changes"])
        for change in result["changes"]:
            kinds[change["kind"]] += 1
            all_changes.append({"batch": bid, "stage": stage, **change})
for bid in sorted(batches):
    b, stages = batches[bid], by_batch.get(bid, {})
    row = [bid, f"{b['first']}-{b['last']}", str(len(b["sections"]))]
    for stage in ("fix", "verify", "recheck"):
        r = stages.get(stage)
        verify = stages.get("verify")
        needs_recheck = isinstance(verify, dict) and bool(verify.get("changes"))
        if r is None and stage == "recheck" and not needs_recheck:
            row.append("-")
            continue
        if not valid_result(r, b):
            failed.append(f"{bid} {stage}: {'not run' if r is None else 'missing or malformed result'}")
            row.append("FAILED")
            continue
        row.append(str(len(r["changes"])))
        for u in r["unresolved"]:
            unresolved.append(f"- {bid} {stage}, {u['file']} p{u['page']}: {u['issue']}")
        if not r["katex_clean"]:
            failed.append(f"{bid} {stage}: reported KaTeX not clean")
    rows.append(row)

files = sorted(chapters.glob("*.md"))
katex = subprocess.run(["node", str(ROOT / "math-review/check_math.js"), *map(str, files)], capture_output=True, text=True)
katex_before = subprocess.run(["node", str(ROOT / "math-review/check_math.js"), *map(str, sorted(original.glob("*.md")))], capture_output=True, text=True)
if katex.returncode:
    failed.append(f"final KaTeX check failed with exit status {katex.returncode}")
# Repository-relative paths, so `patch -p0` from the repository root re-applies the review.
diff_run = subprocess.run(["diff", "-ru", str(original.relative_to(ROOT)), str(chapters.relative_to(ROOT))], cwd=ROOT, capture_output=True, text=True)
if diff_run.returncode not in (0, 1):
    failed.append(f"snapshot diff failed: {diff_run.stderr.strip()}")
diff = diff_run.stdout
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
    f"Status: {'INCOMPLETE' if failed else 'all planned review stages completed'}. Unresolved notes: {len(unresolved)}.",
    f"Batches: {len(batches)}. Section files: {len(files)}, of which {len(changed_files)} changed.",
    f"Display formulas: {sum(d for d, _ in before)} before, {sum(d for d, _ in after)} after. "
    f"Inline formulas: {sum(i for _, i in before)} before, {sum(i for _, i in after)} after.",
    f"KaTeX before: {(katex_before.stdout.strip().splitlines() or [katex_before.stderr.strip() or 'no output'])[-1]}. "
    f"KaTeX after: {(katex.stdout.strip().splitlines() or [katex.stderr.strip() or 'no output'])[-1]}.",
    f"Reported changes across all attempts: fix {stage_changes['fix']}, verify {stage_changes['verify']}, recheck {stage_changes['recheck']}.",
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
    (katex.stdout + katex.stderr).strip(),
    "```",
    "",
    "## Per batch (changes reported by the latest stage attempts)",
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
sys.exit(1 if failed else 0)
