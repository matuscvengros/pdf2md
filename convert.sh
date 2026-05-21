#!/usr/bin/env bash
# Convert PDFs via Docling. Requires `uv` (https://github.com/astral-sh/uv).
#   ./convert.sh                        # convert everything in input/
#   ./convert.sh path/to/file.pdf       # convert a single PDF
#   ./convert.sh --gpu                  # force CUDA GPU (check with `nvidia-smi`)
#   ./convert.sh --cpu                  # force CPU
#   ./convert.sh --gpu path/to/file.pdf # combine with any other flag
#
# With neither --gpu nor --cpu, Docling runs on device="auto": it picks CUDA
# when a working NVIDIA GPU is present and falls back to CPU otherwise. Use
# --cpu explicitly if `auto` is grabbing a GPU you don't want it to use.
set -euo pipefail
cd "$(dirname "$0")"
# convert.py routes its own output: errors -> logs/err.log, everything else -> logs/output.log.
exec uv run convert.py "$@"
