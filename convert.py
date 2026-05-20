import argparse
import re
import traceback
from pathlib import Path

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import ImageRefMode
from docling_core.types.doc.document import (
    ContentLayer,
    DoclingDocument,
    SectionHeaderItem,
)


def build_converter(images_scale: float, formulas: bool, gpu: bool) -> DocumentConverter:
    opts = PdfPipelineOptions()
    opts.generate_picture_images = True
    opts.images_scale = images_scale
    opts.do_formula_enrichment = formulas
    if gpu:
        opts.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CUDA)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


def slugify(text: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^\w\s.-]", "", text).strip().lower()
    s = re.sub(r"[\s_.-]+", "-", s)
    return (s[:maxlen].rstrip("-")) or "section"


def split_into_chapters(
    doc: DoclingDocument,
    chapters_dir: Path,
    images_dir: Path,
    split_level: int,
) -> int:
    # These iteration args must match docling's md serializer; otherwise from_element/to_element indices won't align.
    items = list(
        doc.iterate_items(
            with_groups=True,
            traverse_pictures=True,
            included_content_layers={ContentLayer.BODY},
        )
    )

    if chapters_dir.exists():
        for stale in chapters_dir.glob("*.md"):
            stale.unlink()
    chapters_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    current: tuple[int, str] | None = None

    def flush(start: int, end: int, text: str) -> None:
        nonlocal written
        written += 1
        fname = f"{written:02d}-{slugify(text)}.md"
        doc.save_as_markdown(
            chapters_dir / fname,
            artifacts_dir=images_dir,
            image_mode=ImageRefMode.REFERENCED,
            from_element=start,
            to_element=end,
        )
        print(f"    wrote chapters/{fname}")

    for idx, (item, _level) in enumerate(items):
        if isinstance(item, SectionHeaderItem) and item.level == split_level:
            if current is not None:
                flush(current[0], idx, current[1])
            current = (idx, item.text)
    if current is not None:
        flush(current[0], len(items), current[1])

    return written


def convert_one(
    converter: DocumentConverter,
    pdf: Path,
    output_dir: Path,
    force: bool,
    split: bool,
    split_level: int,
) -> None:
    name = pdf.stem
    out_dir = output_dir / name
    md_path = out_dir / f"{name}.md"
    if md_path.exists() and not force:
        print(f"Skipping {pdf.name} (already converted)")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"

    print(f"Converting {pdf.name} ...")
    result = converter.convert(pdf)
    result.document.save_as_markdown(
        md_path,
        image_mode=ImageRefMode.REFERENCED,
        artifacts_dir=images_dir,
    )
    print(f"  wrote {md_path}")

    if split:
        chapters_dir = out_dir / "chapters"
        n = split_into_chapters(result.document, chapters_dir, images_dir, split_level)
        if n:
            print(f"  split into {n} chapter(s) at H{split_level} in {chapters_dir}")
        else:
            print(f"  no H{split_level} headings found; nothing to split")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDFs to Markdown using Docling.")
    parser.add_argument("file", nargs="?", type=Path, help="Single PDF to convert. If omitted, processes every PDF in --input.")
    parser.add_argument("--input", type=Path, default=Path("input"), help="Input directory (default: input)")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory (default: output)")
    parser.add_argument("--scale", type=float, default=2.0, help="Image scale factor (default: 2.0)")
    parser.add_argument("--no-formulas", action="store_true", help="Disable formula enrichment (faster)")
    parser.add_argument("--force", action="store_true", help="Reconvert PDFs even if output exists")
    parser.add_argument("--no-split", action="store_true", help="Skip splitting into per-chapter files")
    parser.add_argument("--split-level", type=int, default=1, help="Heading level to split chapters on (default: 1)")
    parser.add_argument("--gpu", action="store_true", help="Run model inference on CUDA GPU instead of CPU")
    args = parser.parse_args()

    if args.file is not None:
        if not args.file.is_file():
            parser.error(f"{args.file} is not a file")
        pdfs = [args.file]
    else:
        pdfs = sorted(args.input.glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs found in {args.input}/")
            return

    converter = build_converter(images_scale=args.scale, formulas=not args.no_formulas, gpu=args.gpu)
    print(f"Found {len(pdfs)} PDF(s){' (GPU)' if args.gpu else ''}")
    for pdf in pdfs:
        try:
            convert_one(
                converter,
                pdf,
                args.output,
                args.force,
                split=not args.no_split,
                split_level=args.split_level,
            )
        except Exception as e:
            err_dir = args.output / pdf.stem
            err_dir.mkdir(parents=True, exist_ok=True)
            err_log = err_dir / "error.log"
            err_log.write_text(traceback.format_exc())
            print(f"  failed: {pdf.name}: {e}")
            print(f"  traceback written to {err_log}")


if __name__ == "__main__":
    main()
