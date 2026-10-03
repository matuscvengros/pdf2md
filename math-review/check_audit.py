"""Validate native-agent audit verdicts against a sample and current Markdown.

Usage: .venv/bin/python math-review/check_audit.py SAMPLE_JSON RESULTS_JSON [...]

Results are a flat JSON list with file, line, kind, tex, page and verdict for
each sampled item. Run separately for each sample file. This checks coverage
and stale samples, not the accuracy of the agents' visual judgments.
"""
import argparse
import collections
import json
import re
from pathlib import Path


def identity(item):
    return (str(Path(item["file"]).resolve()), item["line"], item["kind"], item["tex"])


def current_formulas(path):
    src = path.read_text(encoding="utf-8")
    line_at = lambda offset: src.count("\n", 0, offset) + 1
    found = [(line_at(m.start()), "display", m.group(1).strip())
             for m in re.finditer(r"\$\$([\s\S]+?)\$\$", src)]
    masked = re.sub(r"\$\$[\s\S]+?\$\$", lambda m: " " * len(m.group(0)), src)
    found += [(line_at(m.start()), "inline", m.group(1))
              for m in re.finditer(r"(?<![\\$])\$(?!\$)([^$\n]+?)(?<!\\)\$", masked)]
    return collections.Counter(found)


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("sample", type=Path)
parser.add_argument("results", nargs="+", type=Path)
args = parser.parse_args()
sample = json.loads(args.sample.read_text())
expected, bounds = collections.Counter(), {}
errors = []
for group in sample["groups"]:
    path = Path(group["file"])
    sampled = collections.Counter()
    for item in group["items"]:
        key = identity(dict(item, file=str(path)))
        expected[key] += 1
        bounds[key] = (group["first"], group["last"])
        sampled[key[1:]] += 1
    try:
        stale = sampled - current_formulas(path)
        if stale:
            errors.append(f"{path.name}: {sum(stale.values())} samples differ from current Markdown")
    except OSError as exc:
        errors.append(str(exc))

if not expected:
    errors.append("sample contains no formulas")

seen, verdicts = collections.Counter(), collections.Counter()
for path in args.results:
    results = json.loads(path.read_text())
    if not isinstance(results, list):
        errors.append(f"{path.name}: results must be a list")
        continue
    for index, item in enumerate(results, 1):
        try:
            key = identity(item)
            if type(item["line"]) is not int or item["kind"] not in ("display", "inline"):
                raise ValueError("invalid line or kind")
            if key not in bounds:
                raise ValueError("verdict does not identify a sampled formula")
            seen[key] += 1
            verdict = item["verdict"]
            if verdict not in ("correct", "wrong", "unclear", "not-found"):
                raise ValueError("invalid verdict")
            page = item["page"]
            first, last = bounds[key]
            if type(page) is not int or (page != 0 if verdict == "not-found" else not first <= page <= last):
                raise ValueError("page outside sample bounds")
            if verdict == "wrong" and not any(isinstance(item.get(k), str) and item[k].strip()
                                              for k in ("expected", "expected_tex")):
                raise ValueError("wrong verdict needs expected LaTeX")
            verdicts[verdict] += 1
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"{path.name} item {index}: {exc}")

missing, excess = expected - seen, seen - expected
if missing:
    errors.append(f"missing verdicts: {sum(missing.values())}")
if excess:
    errors.append(f"duplicate or extra verdicts: {sum(excess.values())}")
summary = {"sampled": sum(expected.values()), "recorded": sum(seen.values()),
           "verdicts": dict(verdicts), "errors": errors}
print(json.dumps(summary, indent=2))
raise SystemExit(1 if errors or any(verdicts[v] for v in ("wrong", "unclear", "not-found")) else 0)
