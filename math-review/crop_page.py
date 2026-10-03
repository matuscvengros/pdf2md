"""Render a PDF page, or a region of it, to PNG for visual math checks.

Usage: .venv/bin/python math-review/crop_page.py PDF PAGE [X0 Y0 X1 Y1] [--dpi N]
PAGE is the 1-based physical page. X0 Y0 X1 Y1 are fractions of the page width
and height, measured from the top-left corner (default: whole page). Prints the
path of the PNG written under tmp/crops/<pdf-stem>/.
"""
import argparse
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser()
parser.add_argument("pdf", type=Path)
parser.add_argument("page", type=int)
parser.add_argument("box", nargs="*", type=float, default=[0.0, 0.0, 1.0, 1.0])
parser.add_argument("--dpi", type=int, default=300)
args = parser.parse_args()
if len(args.box) != 4 or not all(0 <= v <= 1 for v in args.box) or args.box[0] >= args.box[2] or args.box[1] >= args.box[3]:
    parser.error("box must be X0 Y0 X1 Y1 fractions with X0 < X1 and Y0 < Y1")

page = pdfium.PdfDocument(str(args.pdf))[args.page - 1]
image = page.render(scale=args.dpi / 72).to_pil()
w, h = image.size
x0, y0, x1, y1 = args.box
crop = image.crop((round(x0 * w), round(y0 * h), round(x1 * w), round(y1 * h)))
out_dir = ROOT / "tmp" / "crops" / args.pdf.stem
out_dir.mkdir(parents=True, exist_ok=True)
out = out_dir / f"p{args.page:04d}_{x0:.2f}-{y0:.2f}-{x1:.2f}-{y1:.2f}_{args.dpi}dpi.png"
crop.save(out)
print(out)
