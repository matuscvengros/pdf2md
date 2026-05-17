#!/usr/bin/env bash
# Convert PDFs via Docling. Requires `uv` (https://github.com/astral-sh/uv).
#   ./convert.sh                        # convert everything in input/
#   ./convert.sh path/to/file.pdf       # convert a single PDF
#   ./convert.sh --gpu                  # run inference on CUDA GPU (check with `nvidia-smi`)
#   ./convert.sh --gpu path/to/file.pdf # combine with any other flag
set -euo pipefail
cd "$(dirname "$0")"
exec uv run convert.py "$@"
