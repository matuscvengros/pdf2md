"""Read chronological review journals and validate section ownership of results."""
import collections
import json
import re
from pathlib import Path


def read_stages(journals, batches):
    by_batch = collections.defaultdict(dict)
    attempts = []
    errors = []
    for journal in journals:
        labels, results = {}, {}
        for line_number, line in enumerate(journal.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if rec.get("type") in ("started", "result"):
                    key = rec["key"]
                    if not isinstance(key, str) or not key:
                        raise ValueError("agent key must be a nonempty string")
                    records = labels if rec["type"] == "started" else results
                    if key in records:
                        raise ValueError(f"duplicate {rec['type']} key: {key}")
                    records[key] = rec["label"] if rec["type"] == "started" else rec.get("result")
            except (ValueError, KeyError, AttributeError, TypeError) as err:
                errors.append(f"{journal.name}:{line_number}: malformed journal record: {err}")
        for key, label in labels.items():
            if not isinstance(label, str):
                errors.append(f"{journal.name}: malformed agent label")
                continue
            m = re.match(r"(fix|verify|recheck):(b\d+)(?:\s|$)", label)
            if m:
                bid, stage = m.group(2), m.group(1)
                if bid not in batches:
                    errors.append(f"unknown batch in journal: {label}")
                else:
                    # A new fix invalidates earlier verification; a new verifier's
                    # edits invalidate an earlier recheck, including across reruns.
                    for later in (("verify", "recheck") if stage == "fix" else ("recheck",) if stage == "verify" else ()):
                        by_batch[bid].pop(later, None)
                    result = results.get(key, "MISSING")
                    by_batch[bid][stage] = result
                    attempts.append((bid, stage, result))
    return by_batch, attempts, errors


def valid_result(result, batch, root, chapters):
    if not isinstance(result, dict):
        return False
    if not isinstance(result.get("katex_clean"), bool):
        return False
    for count in ("display_equations_checked", "inline_expressions_checked"):
        if type(result.get(count)) is not int or result[count] < 0:
            return False
    owned = {s[0]: (s[1], s[2]) for s in batch["sections"]}
    for field, required in (("changes", ("file", "page", "kind", "before", "after")), ("unresolved", ("file", "page", "issue"))):
        if not isinstance(result.get(field), list):
            return False
        for item in result[field]:
            if not isinstance(item, dict) or any(k not in item for k in required):
                return False
            if not isinstance(item["file"], str) or type(item["page"]) is not int:
                return False
            item_path = Path(item["file"])
            if len(item_path.parts) > 1:
                resolved = item_path if item_path.is_absolute() else root / item_path
                if resolved.resolve().parent != chapters.resolve():
                    return False
            bounds = owned.get(item_path.name)
            if bounds is None or not bounds[0] <= item["page"] <= bounds[1]:
                return False
            if any(not isinstance(item[k], str) for k in required if k != "page"):
                return False
            if field == "changes" and item["kind"] not in {"display", "inline", "table", "missing-equation", "not-decoded", "equation-number", "revert", "other"}:
                return False
    return True
