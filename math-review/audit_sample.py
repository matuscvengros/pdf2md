"""Draw a random sample of formulas from a reviewed book for an independent audit.

Picks --files random section files that contain math (weighted by how much math
they hold) and up to --per-file random formulas from each, display and inline.
Writes tmp/math-review/<stem>/<NAME>.json (default audit-args.json) for math-review/audit.js.

Usage: .venv/bin/python math-review/audit_sample.py BOOK_STEM [--files 10] [--per-file 12] [--seed 1] [--kind all|display|inline] [--out NAME]
"""
import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser()
parser.add_argument("stem")
parser.add_argument("--files", type=int, default=10)
parser.add_argument("--per-file", type=int, default=12)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--kind", choices=("all", "display", "inline"), default="all")
parser.add_argument("--out", default="audit-args")
args = parser.parse_args()

work = ROOT / "tmp" / "math-review" / args.stem
plan = json.loads((work / "args.json").read_text())
pages = {s[0]: (s[1], s[2]) for b in plan["batches"] for s in b["sections"]}
rng = random.Random(args.seed)


def formulas(path: Path) -> list[dict]:
    src = path.read_text(encoding="utf-8")
    line_at = lambda offset: src.count("\n", 0, offset) + 1  # noqa: E731
    found = [{"kind": "display", "line": line_at(m.start()), "tex": m.group(1).strip()} for m in re.finditer(r"\$\$([\s\S]+?)\$\$", src)]
    masked = re.sub(r"\$\$[\s\S]+?\$\$", lambda m: " " * len(m.group(0)), src)
    found += [{"kind": "inline", "line": line_at(m.start()), "tex": m.group(1)} for m in re.finditer(r"(?<![\\$])\$(?!\$)([^$\n]+?)(?<!\\)\$", masked)]
    return found


candidates = {p.name: [f for f in formulas(p) if args.kind in ("all", f["kind"])] for p in sorted(Path(plan["chapters"]).glob("*.md"))}
candidates = {name: items for name, items in candidates.items() if items}
names = list(candidates)
chosen = []
while len(chosen) < min(args.files, len(names)):
    name = rng.choices(names, weights=[len(candidates[n]) for n in names])[0]
    if name not in chosen:
        chosen.append(name)
groups = []
for name in chosen:
    items = rng.sample(candidates[name], min(args.per_file, len(candidates[name])))
    first, last = pages[name]
    groups.append({"file": f"{plan['chapters']}/{name}", "first": first, "last": last, "items": sorted(items, key=lambda i: i["line"])})
out = work / f"{args.out}.json"
out.write_text(json.dumps({k: plan[k] for k in ("root", "title", "pdf", "pages", "pagePad")} | {"groups": groups}, indent=1))
print(f"{sum(len(g['items']) for g in groups)} formulas from {len(groups)} files -> {out}")
