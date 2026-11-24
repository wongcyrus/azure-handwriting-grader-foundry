import hashlib
import json
import math
import tempfile
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .errors import ApplicationError
from .preflight import ENGINE_COMMIT, engine_functions

DPI = 200
MAX_PAGE_PIXELS = 4_000_000
MAX_TEMPLATE_PIXELS = 24_000_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
RENDER_LOCK = Lock()


def review_hash(regions: dict) -> str:
    payload = {key: value for key, value in regions.items() if key != "review_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def render_template(document: dict, content: bytes) -> tuple[dict, list[tuple[str, bytes]]]:
    engine_functions()
    try:
        import pypdfium2 as pdfium
        from handwriting_grader.regions import prepare_regions
    except ImportError as error:
        raise ApplicationError(
            "ENGINE_UNAVAILABLE", "The pinned PDF renderer is required.", 503
        ) from error
    count = document["settings"]["pages_per_student"]
    # PDFium is not thread-safe; serialize native rendering within this process.
    with RENDER_LOCK, tempfile.TemporaryDirectory(prefix="foundry-regions-") as directory:
        root = Path(directory)
        (root / "scans.pdf").write_bytes(content)
        try:
            pdf = pdfium.PdfDocument(str(root / "scans.pdf"))
            try:
                pixels = 0
                for index in range(count):
                    page = pdf[index]
                    try:
                        width, height = page.get_size()
                    finally:
                        page.close()
                    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                        raise ValueError("Invalid page dimensions.")
                    page_pixels = math.ceil(width * DPI / 72) * math.ceil(height * DPI / 72)
                    if page_pixels > MAX_PAGE_PIXELS:
                        raise ApplicationError("RENDER_LIMIT", "Page exceeds 4 million pixels.")
                    pixels += page_pixels
                if pixels > MAX_TEMPLATE_PIXELS:
                    raise ApplicationError("RENDER_LIMIT", "Template exceeds 24 million pixels.")
            finally:
                pdf.close()
            config = {
                "exam": {
                    "scanned_pdf": "scans.pdf",
                    "output_dir": "output",
                },
                "layout": {"pages_per_student": count},
            }
            target = prepare_regions(config, root, count)
            manifest = json.loads((target / "manifest.json").read_text())
            if manifest["pdf_sha256"] != document["artifacts"]["scans"]["sha256"]:
                raise ValueError("Rendered source hash mismatch.")
            if len(manifest["pages"]) != count:
                raise ValueError("Unexpected rendered page count.")
            pages, artifacts = [], []
            for index, dimensions in enumerate(manifest["pages"]):
                image = (target / "images" / f"{index}.jpg").read_bytes()
                if (
                    dimensions["width"] * dimensions["height"] > MAX_PAGE_PIXELS
                    or len(image) > MAX_IMAGE_BYTES
                ):
                    raise ApplicationError("RENDER_LIMIT", "Rendered image exceeds local limits.")
                if hashlib.sha256(image).hexdigest() != dimensions["sha256"]:
                    raise ValueError("Rendered image hash mismatch.")
                artifact_id = str(uuid4())
                pages.append({**dimensions, "index": index, "artifact_id": artifact_id})
                artifacts.append((artifact_id, image))
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError(
                "INVALID_RENDER", "The first script could not be rendered."
            ) from error
    regions = {
        "policy_version": 1,
        "engine_commit": ENGINE_COMMIT,
        "snapshot_sha256": document["snapshot_sha256"],
        "source_pdf_sha256": document["artifacts"]["scans"]["sha256"],
        "dpi": DPI,
        "coordinate_space": "rendered_page_pixels",
        "origin": "top_left",
        "template": "first_present_script",
        "pages": pages,
        "question_labels": document["preflight"]["question_labels"],
        "annotations": {str(index): [] for index in range(count)},
        "reviewed_pages": [],
        "revision": 0,
    }
    regions["review_sha256"] = review_hash(regions)
    return regions, artifacts


def validate_regions(regions: dict, *, complete: bool = False) -> None:
    engine_functions()
    from handwriting_grader.regions import validate_annotations
    from handwriting_grader.rubric import question_key

    try:
        validate_annotations(regions["annotations"], regions["pages"], complete=complete)
        reviewed = regions["reviewed_pages"]
        indexes = set(range(len(regions["pages"])))
        if len(set(reviewed)) != len(reviewed) or not set(reviewed).issubset(indexes):
            raise ValueError("Reviewed pages must be unique template page indexes.")
        actual = {
            question_key(box["label"])
            for boxes in regions["annotations"].values()
            for box in boxes
            if box["label"] not in {"NAME", "ID", "CLASS"}
        }
        expected = {question_key(label) for label in regions["question_labels"]}
        if not actual.issubset(expected):
            raise ValueError("Every question box must match the reviewed rubric.")
        if complete and (actual != expected or set(reviewed) != indexes):
            raise ValueError("Review every template page and cover every rubric question.")
    except (ValueError, TypeError, KeyError) as error:
        raise ApplicationError("INVALID_REGIONS", str(error)) from error
