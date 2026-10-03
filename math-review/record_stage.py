"""Record native-agent review stages in a report.py-compatible journal.

Start: record_stage.py JOURNAL ARGS_JSON BATCH STAGE
Finish: same arguments plus --key KEY --result RESULT_JSON
Prints the new key on start. Uses a POSIX file lock for parallel writers.
This records review evidence; it does not run agents or certify visual accuracy.
"""
import argparse
import fcntl
import json
import re
import uuid
from pathlib import Path

from journal import valid_result

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("journal", type=Path, help="Append-only journal under logs/")
parser.add_argument("args", type=Path, help="JSON from plan.py")
parser.add_argument("batch", help="Batch ID from the plan")
parser.add_argument("stage", choices=("fix", "verify", "recheck"))
parser.add_argument("--key", help="Key returned when starting this stage")
parser.add_argument("--result", type=Path, help="Review result JSON under tmp/")
args = parser.parse_args()
if bool(args.key) != bool(args.result):
    parser.error("--key and --result must be supplied together")
if not args.journal.resolve().is_relative_to(ROOT / "logs"):
    parser.error("journal must be under this repository's logs/")
if args.result and not args.result.resolve().is_relative_to(ROOT / "tmp"):
    parser.error("result must be under this repository's tmp/")

try:
    plan = json.loads(args.args.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    parser.error(str(exc))
if (not isinstance(plan, dict) or not isinstance(plan.get("root"), str)
        or Path(plan["root"]).resolve() != ROOT
        or not isinstance(plan.get("chapters"), str)):
    parser.error("plan must identify this checkout and its chapters directory")
chapters = Path(plan["chapters"]).resolve()
if not chapters.is_relative_to(ROOT / "output"):
    parser.error("chapters must be under this repository's output/")
items = plan.get("batches")
if not isinstance(items, list) or not items:
    parser.error("plan requires nonempty batches")
batches, owned = {}, set()
for batch in items:
    if (not isinstance(batch, dict) or not isinstance(batch.get("id"), str)
            or not re.fullmatch(r"b\d+", batch["id"]) or batch["id"] in batches):
        parser.error("batches require unique b-number IDs")
    if (type(batch.get("first")) is not int or type(batch.get("last")) is not int
            or not 1 <= batch["first"] <= batch["last"]
            or not isinstance(batch.get("sections"), list) or not batch["sections"]):
        parser.error("batches require valid page ranges and nonempty sections")
    for section in batch["sections"]:
        if (not isinstance(section, list) or len(section) != 3
                or not isinstance(section[0], str) or Path(section[0]).name != section[0]
                or not section[0].endswith(".md")
                or type(section[1]) is not int or type(section[2]) is not int
                or not batch["first"] <= section[1] <= section[2] <= batch["last"]):
            parser.error("sections require Markdown filenames and pages within their batch")
        if section[0] in owned:
            parser.error("a section is assigned to more than one batch")
        owned.add(section[0])
    batches[batch["id"]] = batch
if args.batch not in batches:
    parser.error("unknown batch")
batch = batches[args.batch]
label = f"{args.stage}:{args.batch} p{batch['first']}-{batch['last']}"
key = args.key or "native:" + str(uuid.uuid4())
if args.result:
    try:
        result = json.loads(args.result.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if not valid_result(result, batch, ROOT, chapters):
        parser.error("malformed result or change outside this batch's section/page ownership")
    record = {"type": "result", "key": key, "result": result, "native": True}
else:
    record = {"type": "started", "key": key, "label": label, "native": True}

args.journal.parent.mkdir(parents=True, exist_ok=True)
with args.journal.open("a+", encoding="utf-8") as stream:
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    stream.seek(0)
    started, finished = {}, set()
    for line_number, line in enumerate(stream, 1):
        if not line.endswith("\n"):
            parser.error(f"journal line {line_number}: unterminated record; repair the journal before appending")
        if not line.strip():
            continue
        try:
            prior = json.loads(line)
            if prior.get("type") not in ("started", "result"):
                continue
            prior_key = prior["key"]
            if not isinstance(prior_key, str) or not prior_key:
                raise ValueError("invalid key")
            if prior["type"] == "started":
                if prior_key in started or not isinstance(prior.get("label"), str):
                    raise ValueError("duplicate start or invalid label")
                started[prior_key] = prior["label"]
            else:
                if prior_key not in started or prior_key in finished:
                    raise ValueError("orphan or duplicate result")
                finished.add(prior_key)
        except (ValueError, KeyError, AttributeError, TypeError) as exc:
            parser.error(f"journal line {line_number}: {exc}")
    if args.result:
        if started.get(key) != label:
            parser.error("key does not identify a prior start of this batch/stage/page range")
        if key in finished:
            parser.error("result already recorded; start a new stage for a retry")
    elif key in started:
        parser.error("stage key already exists")
    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    stream.flush()
if not args.result:
    print(key)
