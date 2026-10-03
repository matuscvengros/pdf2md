import argparse
import hashlib
import logging
import math
import re
import sys
import traceback
from pathlib import Path


def _log_name(value: str) -> str:
    if not re.fullmatch(r"[\w.-]+", value):
        raise argparse.ArgumentTypeError("must contain only letters, digits, '.', '_' or '-'")
    return value


# Parsed before the full CLI so concurrent runs can write separate logs.
_LOG_ARGS = argparse.ArgumentParser(add_help=False)
_LOG_ARGS.add_argument("--log-name", type=_log_name, help="Write logs/<NAME>-err.log and logs/<NAME>-output.log instead of the shared logs/err.log and logs/output.log. Use a distinct name for each concurrent run.")
_LOG_NAME = _LOG_ARGS.parse_known_args()[0].log_name

# Route logs before importing docling so its loggers attach to our handlers.
LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
_ERR_LOG = LOGS_DIR / (f"{_LOG_NAME}-err.log" if _LOG_NAME else "err.log")
_OUT_LOG = LOGS_DIR / (f"{_LOG_NAME}-output.log" if _LOG_NAME else "output.log")
_ERR_LOG.write_text("")
_OUT_LOG.write_text("")

_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_err_handler = logging.FileHandler(_ERR_LOG, mode="a")
_err_handler.setLevel(logging.ERROR)
_err_handler.setFormatter(_fmt)
_out_handler = logging.FileHandler(_OUT_LOG, mode="a")
_out_handler.setLevel(logging.DEBUG)
_out_handler.addFilter(lambda r: r.levelno < logging.ERROR)
_out_handler.setFormatter(_fmt)
_root = logging.getLogger()
_root.setLevel(logging.DEBUG)
_root.addHandler(_err_handler)
_root.addHandler(_out_handler)

# Anything written to stderr (tqdm bars, transformers warnings, raw prints from
# C extensions) is noise for the terminal — funnel it into output.log too.
sys.stderr = open(_OUT_LOG, "a", buffering=1)

from docling.backend.docling_parse_backend import (
    DoclingParseDocumentBackend,
    DoclingParsePageBackend,
)
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.models.stages.reading_order import readingorder_model
from docling.utils.locks import pypdfium2_lock
from docling_core.types.doc import BoundingBox, CoordOrigin, ImageRefMode
from docling_core.types.doc.document import (
    ContentLayer,
    DoclingDocument,
    SectionHeaderItem,
)
from docling_ibm_models.reading_order.reading_order_rb import PageElement, ReadingOrderPredictor
from PIL import Image


class SafeCropPageBackend(DoclingParsePageBackend):
    def get_page_image(self, scale: float = 1, cropbox: BoundingBox | None = None) -> Image.Image:
        try:
            return super().get_page_image(scale=scale, cropbox=cropbox)
        except ValueError:
            if cropbox is None:
                raise
        # pypdfium2 rejects a crop that leaves less than one pixel. A degenerate
        # element box asks for one, and the error would fail the whole PDF, so
        # render the box clamped into the page instead.
        size = self.get_size()
        box = cropbox.to_top_left_origin(size.height)
        left = min(max(box.l, 0.0), size.width - 1)
        top = min(max(box.t, 0.0), size.height - 1)
        safe = BoundingBox(
            l=left,
            t=top,
            r=min(max(box.r, left + 1), size.width),
            b=min(max(box.b, top + 1), size.height),
            coord_origin=CoordOrigin.TOPLEFT,
        )
        logging.getLogger("pdf2md").warning(
            "page %d: crop %s does not fit the page, rendering %s instead", self._page_no + 1, box, safe
        )
        return super().get_page_image(scale=scale, cropbox=safe)


class SafeCropDocumentBackend(DoclingParseDocumentBackend):
    # Same as DoclingParseDocumentBackend.load_page, but returns SafeCropPageBackend.
    def load_page(self, page_no: int, create_words: bool = True, create_textlines: bool = True) -> SafeCropPageBackend:
        assert self.dp_doc is not None
        with pypdfium2_lock:
            ppage = self._pdoc[page_no]
        return SafeCropPageBackend(
            dp_doc=self.dp_doc,
            page_obj=ppage,
            page_no=page_no,
            create_words=create_words,
            create_textlines=create_textlines,
        )


class SafeReadingOrderPredictor(ReadingOrderPredictor):
    def _predict_page(self, page_elements: list[PageElement]) -> list[PageElement]:
        ordered = super()._predict_page(page_elements)
        kept = {element.cid for element in ordered}
        missing = [element for element in page_elements if element.cid not in kept]
        if not missing:
            return ordered
        # A cycle in Docling's reading-order graph can leave body elements
        # unreachable. Its geometric comparator also orders graph heads and
        # children; use it for this page group rather than dropping content.
        logging.getLogger("pdf2md").warning(
            "reading-order fallback page %d: recovered %d omitted element(s); "
            "using geometric order, review this page against the PDF",
            page_elements[0].page_no,
            len(missing),
        )
        return sorted(page_elements)


def build_converter(
    images_scale: float,
    formulas: bool,
    gpu: bool,
    cpu: bool,
    ocr_language: str | None = None,
    force_ocr: bool = False,
) -> DocumentConverter:
    # ReadingOrderModel constructs this predictor when the PDF pipeline starts.
    # Keep the adapter in sync with Docling's private _predict_page API.
    readingorder_model.ReadingOrderPredictor = SafeReadingOrderPredictor
    opts = PdfPipelineOptions()
    opts.generate_picture_images = True
    opts.images_scale = images_scale
    opts.do_formula_enrichment = formulas
    # Default: leave accelerator_options unset so Docling uses device="auto",
    # which picks CUDA when a working NVIDIA GPU is present and CPU otherwise.
    # --gpu forces CUDA; --cpu forces CPU.
    if gpu:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("--gpu requires CUDA-enabled PyTorch and a usable NVIDIA GPU")
        try:
            torch.ones(1, device="cuda").sum().item()
        except RuntimeError as exc:
            raise RuntimeError(f"--gpu CUDA check failed: {exc}") from exc
        opts.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CUDA)
    elif cpu:
        opts.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    if gpu or ocr_language is not None:
        from rapidocr import LangDet, LangRec

        language = ocr_language or "chinese"
        # Set the engine's language too; lang alone does not select its models.
        # The default ONNX runtime can run OCR on CPU despite CUDA acceleration.
        opts.ocr_options = RapidOcrOptions(
            backend="torch",
            lang=[language],
            rapidocr_params={
                "Det.lang_type": LangDet.EN if language == "english" else LangDet.CH,
                "Rec.lang_type": LangRec.EN if language == "english" else LangRec.CH,
            },
        )
    opts.ocr_options.force_full_page_ocr = force_ocr
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts, backend=SafeCropDocumentBackend)}
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
    # save_as_markdown deep-copies the document and re-saves every picture on each
    # call, so one call per section costs sections x pictures. Do its picture step
    # once, then serialize each section from that copy exactly as it would.
    ref_doc: DoclingDocument | None = None

    def flush(start: int, end: int, text: str) -> None:
        nonlocal written, ref_doc
        if ref_doc is None:
            ref_doc = doc._with_pictures_refs(image_dir=images_dir, page_no=None, reference_path=chapters_dir)
        written += 1
        fname = f"{written:02d}-{slugify(text)}.md"
        (chapters_dir / fname).write_text(
            ref_doc.export_to_markdown(
                from_element=start,
                to_element=end,
                image_mode=ImageRefMode.REFERENCED,
            ),
            encoding="utf-8",
        )
        pages = [prov.page_no for item, _ in items[start:end] for prov in getattr(item, "prov", [])]
        logging.getLogger("pdf2md").info(
            "section chapters/%s pages %s-%s", fname, min(pages, default="?"), max(pages, default="?")
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
    split_level: int,
    page_start: int = 1,
    page_end: int | None = None,
) -> None:
    name = pdf.stem
    suffix = ""
    if page_start != 1 or page_end is not None:
        end_tag = f"{page_end:04d}" if page_end is not None else "end"
        suffix = f"-pages-{page_start:04d}-{end_tag}"
    out_dir = output_dir / f"{name}{suffix}"
    chapters_dir = out_dir / "chapters"
    conversion_id = hashlib.sha256(
        f"{out_dir.resolve()}|heading-sections|H{split_level}".encode()
    ).hexdigest()[:16]
    completion_log = LOGS_DIR / f"converted-{conversion_id}.log"
    if completion_log.is_file() and not force:
        outputs = completion_log.read_text(encoding="utf-8").splitlines()
        if outputs and all((out_dir / path).is_file() for path in outputs):
            print(f"Skipping {pdf.name} (chapters already converted)")
            return

    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir = out_dir / "images"

    print(f"Converting {pdf.name} ...")
    result = converter.convert(pdf, page_range=(page_start, page_end or sys.maxsize))
    if result.status != ConversionStatus.SUCCESS:
        raise RuntimeError(f"Docling conversion did not fully succeed: {result.status.value}")
    if page_end is not None and page_end > result.input.page_count:
        raise ValueError(f"--page-end {page_end} exceeds the PDF's {result.input.page_count} pages")
    completion_log.unlink(missing_ok=True)
    n = split_into_chapters(result.document, chapters_dir, images_dir, split_level)

    # Docling saves picture artifacts before applying element slicing. Keep only
    # images referenced by the exported chapters, including after reconversion.
    chapter_paths = sorted(chapters_dir.glob("*.md"))
    referenced_images = {
        filename
        for path in chapter_paths
        for filename in re.findall(
            r"!\[[^\]]*\]\(\.\./images/([^)]+)\)",
            path.read_text(encoding="utf-8"),
        )
    }
    for image in images_dir.glob("image_*.png"):
        if image.name not in referenced_images:
            image.unlink()

    # Remove artifacts from the previous combined/chunked output format.
    for legacy in (out_dir / f"{name}.md", out_dir / f"{name}.json"):
        legacy.unlink(missing_ok=True)
    chunks_dir = out_dir / "chunks"
    if chunks_dir.is_dir():
        for legacy in chunks_dir.glob("pages-*.md"):
            legacy.unlink()
        if not any(chunks_dir.iterdir()):
            chunks_dir.rmdir()

    outputs = chapter_paths + sorted(images_dir.glob("image_*.png"))
    completion_log.write_text(
        "\n".join(path.relative_to(out_dir).as_posix() for path in outputs) + "\n",
        encoding="utf-8",
    )
    print(f"  wrote {n} chapter(s) in {chapters_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDFs to heading-based Markdown sections using Docling.", parents=[_LOG_ARGS])
    parser.add_argument("file", nargs="?", type=Path, help="Single PDF to convert. If omitted, processes every PDF in --input.")
    parser.add_argument("--input", type=Path, default=Path("input"), help="Input directory (default: input)")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory (default: output)")
    parser.add_argument("--scale", type=float, default=2.0, help="Image scale factor (default: 2.0)")
    parser.add_argument("--no-formulas", action="store_true", help="Disable formula enrichment (faster)")
    parser.add_argument("--force", action="store_true", help="Reconvert PDFs even if output exists")
    parser.add_argument("--split-level", type=int, default=1, help="Heading level to split chapters on (default: 1)")
    parser.add_argument("--page-start", type=int, default=1, help="First physical PDF page, 1-based inclusive (default: 1)")
    parser.add_argument("--page-end", type=int, help="Last physical PDF page, 1-based inclusive (default: final page)")
    parser.add_argument("--ocr-language", choices=("english", "chinese"), help="Select RapidOCR models for this language (default: Docling OCR selection)")
    parser.add_argument("--force-ocr", action="store_true", help="OCR entire pages instead of using the PDF's embedded text layer (use for damaged text layers).")
    device = parser.add_mutually_exclusive_group()
    device.add_argument("--gpu", action="store_true", help="Force CUDA GPU. Default leaves Docling on device='auto', which picks CUDA when a working NVIDIA GPU is present and CPU otherwise.")
    device.add_argument("--cpu", action="store_true", help="Force CPU, even if a usable GPU is present (use this if 'auto' is picking up a wedged GPU).")
    args = parser.parse_args()

    if args.page_start < 1:
        parser.error("--page-start must be positive")
    if args.page_end is not None and args.page_end < args.page_start:
        parser.error("--page-end must be at least --page-start")
    if not math.isfinite(args.scale) or args.scale <= 0:
        parser.error("--scale must be positive and finite")
    if not 1 <= args.split_level <= 6:
        parser.error("--split-level must be between 1 and 6")

    if args.file is not None:
        if not args.file.is_file():
            parser.error(f"{args.file} is not a file")
        pdfs = [args.file]
    else:
        pdfs = sorted(args.input.glob("*.pdf"))
        if not pdfs:
            print(f"No PDFs found in {args.input}/")
            return

    try:
        converter = build_converter(
            images_scale=args.scale,
            formulas=not args.no_formulas,
            gpu=args.gpu,
            cpu=args.cpu,
            ocr_language=args.ocr_language,
            force_ocr=args.force_ocr,
        )
    except (ImportError, RuntimeError) as exc:
        print(f"Cannot initialize converter: {exc} (see {_OUT_LOG})")
        parser.error(str(exc))
    device_tag = " (GPU)" if args.gpu else " (CPU)" if args.cpu else " (auto)"
    print(f"Found {len(pdfs)} PDF(s){device_tag}")
    failed = 0
    for pdf in pdfs:
        try:
            convert_one(
                converter,
                pdf,
                args.output,
                args.force,
                split_level=args.split_level,
                page_start=args.page_start,
                page_end=args.page_end,
            )
        except Exception as e:
            failed += 1
            logging.getLogger("pdf2md").error(
                "failed: %s\n%s", pdf.name, traceback.format_exc()
            )
            print(f"  failed: {pdf.name}: {e} (see {_ERR_LOG})")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
