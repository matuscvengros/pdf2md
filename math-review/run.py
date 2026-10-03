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
options = parser.parse_args()
if options.only and options.kind != "review":
    parser.error("--only applies to review batches")
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
if options.only:
    available = {batch["id"] for batch in items}
    if set(options.only) - available:
        parser.error("--only contains unknown batch IDs")
    arguments["only"] = options.only

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
    "If Workflow is unavailable, report that failure and stop. "
    "Wait for the workflow's completion notifications. Report failed batches, "
    "unresolved items, and the transcript directory containing journal.jsonl. "
    "Do not describe partial or failed work as complete."
)
(work / f"{options.log_name}-prompt.txt").write_text(prompt, encoding="utf-8")
stream = logs / f"{options.log_name}-workflow.jsonl"
errors = logs / f"{options.log_name}-workflow-err.log"
command = [
    claude, "--print", "--no-session-persistence", "--output-format", "stream-json",
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
