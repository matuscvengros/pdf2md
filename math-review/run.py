"""Run a math review or sample audit through the local Claude Code Workflow tool.

Usage: .venv/bin/python math-review/run.py ARGS_JSON --log-name NAME
Add --kind audit for audit args, or --only b001 b002 for selected review batches.
The authenticated Claude CLI must expose Workflow. Its default model is retained.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from journal import read_stages, valid_result

ROOT = Path(__file__).resolve().parent.parent


def log_name(value: str) -> str:
    if not re.fullmatch(r"[\w.-]+", value):
        raise argparse.ArgumentTypeError("use only letters, digits, '.', '_' or '-'")
    return value


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("args", type=Path, help="JSON from plan.py or audit_sample.py")
parser.add_argument("--log-name", required=True, type=log_name, help="Distinct prefix for this run's logs")
parser.add_argument("--kind", choices=("review", "audit"), default="review")
parser.add_argument("--only", nargs="+", help="Run only these review batch IDs")
parser.add_argument("--resume-journals", nargs="+", type=Path,
                    help="Reuse successful current stages from journals, oldest first")
options = parser.parse_args()
if options.only and options.kind != "review":
    parser.error("--only applies to review batches")
if options.resume_journals and options.kind != "review":
    parser.error("--resume-journals applies to review batches")
claude = shutil.which("claude")
if claude is None:
    parser.error("authenticated Claude Code CLI with the Workflow tool is required")
try:
    arguments = json.loads(options.args.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:
    parser.error(str(exc))
if not isinstance(arguments, dict) or Path(arguments.get("root", "")).resolve() != ROOT:
    parser.error("args.root must be this repository checkout")
items = arguments.get("batches" if options.kind == "review" else "groups")
if not isinstance(items, list) or not items:
    parser.error("args must contain nonempty batches or audit groups")
if options.kind == "review":
    batches, owned = {}, set()
    for batch in items:
        if (not isinstance(batch, dict) or not isinstance(batch.get("id"), str)
                or not re.fullmatch(r"b\d+", batch["id"])
                or batch["id"] in batches):
            parser.error("review batches require unique b-number IDs")
        if (type(batch.get("first")) is not int or type(batch.get("last")) is not int
                or not 1 <= batch["first"] <= batch["last"]
                or not isinstance(batch.get("sections"), list) or not batch["sections"]):
            parser.error("review batches require valid page ranges and nonempty sections")
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
    selected = options.only if options.only is not None else arguments.get("only")
    if selected is not None:
        if (not isinstance(selected, list) or any(not isinstance(bid, str) for bid in selected)
                or set(selected) - batches.keys()):
            parser.error("only must contain known review batch IDs")
        arguments["only"] = selected
        if not selected:
            print("No review batches selected.")
            raise SystemExit(0)
if options.resume_journals:
    try:
        stages, _, errors = read_stages(options.resume_journals, batches)
    except OSError as exc:
        parser.error(str(exc))
    if errors:
        parser.error("; ".join(errors))
    chapters = Path(arguments["chapters"])
    resumed = {}
    pending = []
    for bid, batch in batches.items():
        current = {}
        for stage in ("fix", "verify", "recheck"):
            result = stages.get(bid, {}).get(stage)
            if not valid_result(result, batch, ROOT, chapters) or not result["katex_clean"]:
                break
            current[stage] = result
        resumed[bid] = current
        verify = current.get("verify")
        complete = verify is not None and (not verify["changes"] or "recheck" in current)
        if not complete and (selected is None or bid in selected):
            pending.append(bid)
    arguments["resume"] = resumed
    arguments["only"] = pending
    if not pending:
        print("All selected review stages are already recorded; run report.py with all journals.")
        raise SystemExit(0)

work = ROOT / "tmp" / "math-review" / "runs"
work.mkdir(parents=True, exist_ok=True)
logs = ROOT / "logs"
logs.mkdir(exist_ok=True)
args_file = work / f"{options.log_name}-args.json"
args_file.write_text(json.dumps(arguments, ensure_ascii=False), encoding="utf-8")
script = ROOT / "math-review" / ("workflow.js" if options.kind == "review" else "audit.js")
scope = (
    "Run disjoint batches in parallel. Each batch requires a fixer, a fresh adversarial "
    "verifier that expects missed or introduced errors, and a third checker of verifier "
    "edits. Follow the script's visual comparison and KaTeX rules."
    if options.kind == "review" else
    "This is a read-only sample audit. Return one verdict for every sampled formula."
)
prompt = (
    "Use the Workflow tool to run the authorized math work in this repository. "
    f"Read {args_file} and pass the parsed JSON object as args, not a string, "
    f"to Workflow with scriptPath {script}. {scope} "
    "Do not convert books, change tooling, run Git commands, or send messages. "
    "Keep temporary files under the repository tmp/ and logs under logs/. "
    "When args.resume contains prior results, reuse them as directed by the script; "
    "run only the missing stages. Prior journals remain required for the final report. "
    "If Workflow is unavailable, report that failure and stop. "
    "Wait for the workflow's completion notifications. Report failed batches, "
    "unresolved items, and the transcript directory containing journal.jsonl. "
    "Do not describe partial or failed work as complete."
)
(work / f"{options.log_name}-prompt.txt").write_text(prompt, encoding="utf-8")
stream = logs / f"{options.log_name}-workflow.jsonl"
errors = logs / f"{options.log_name}-workflow-err.log"
command = [
    claude, "--print", "--output-format", "stream-json",
    "--verbose", "--permission-mode", "acceptEdits", "--allowedTools", "Workflow,Read,Bash,Edit",
]
print(f"Running {options.kind}; stream {stream.relative_to(ROOT)}", flush=True)
with stream.open("w", encoding="utf-8") as output, errors.open("w", encoding="utf-8") as error:
    result = subprocess.run(
        command, input=prompt, text=True, stdout=output, stderr=error, cwd=ROOT,
        env=dict(os.environ, TMPDIR=str(ROOT / "tmp")),
    )
print(f"Workflow CLI exit status: {result.returncode}. Check its journal with report.py.")
raise SystemExit(result.returncode)
