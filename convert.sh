#!/usr/bin/env bash
# Convert PDFs via Docling. Requires `uv` (https://github.com/astral-sh/uv).
#   ./convert.sh                  # convert everything in input/
#   ./convert.sh path/to/file.pdf # convert a single PDF
set -euo pipefail
cd "$(dirname "$0")"
exec uv run convert.py "$@"
