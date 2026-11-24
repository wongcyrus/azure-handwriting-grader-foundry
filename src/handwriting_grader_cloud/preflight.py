import json
import math
import tempfile
import zipfile
from importlib.metadata import PackageNotFoundError, distribution
from io import BytesIO
from pathlib import Path
from typing import Protocol

from .errors import ApplicationError

ENGINE_COMMIT = "3b155f9232cb0730587d89677c932ea049dd7f71"
MAX_EXPANDED_WORKBOOK_BYTES = 16 * 1024 * 1024
MAX_WORKBOOK_ENTRIES = 1000
MAX_PDF_PAGES = 200


class InputValidator(Protocol):
    def validate(self, document: dict, contents: dict[str, bytes]) -> dict: ...


def engine_functions():
    try:
        metadata = distribution("azure-handwriting-grader-skills")
        source = json.loads(metadata.read_text("direct_url.json") or "{}")
    except PackageNotFoundError as error:
        raise ApplicationError(
            "ENGINE_UNAVAILABLE", "Install the pinned engine extra before input review.", 503
        ) from error
    except (ValueError, TypeError, OSError) as error:
        raise ApplicationError(
            "ENGINE_PIN_MISMATCH", "Engine provenance is invalid.", 503
        ) from error
    if not isinstance(source, dict) or not isinstance(source.get("vcs_info"), dict):
        raise ApplicationError(
            "ENGINE_PIN_MISMATCH", "The pinned engine provenance is required.", 503
        )
    if source["vcs_info"].get("commit_id") != ENGINE_COMMIT:
        raise ApplicationError(
            "ENGINE_PIN_MISMATCH", "The installed engine is not the approved pin.", 503
        )
    try:
        from handwriting_grader.cli import check_exam
        from handwriting_grader.rubric import read_rubric
    except ImportError as error:
        raise ApplicationError(
            "ENGINE_UNAVAILABLE", "The pinned engine dependencies are unavailable.", 503
        ) from error
    return check_exam, read_rubric


def check_workbook(content: bytes) -> None:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_WORKBOOK_ENTRIES:
            raise ValueError("Workbook has too many archive entries.")
        if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(archive.namelist()):
            raise ValueError("An XLSX workbook is required.")
        if sum(entry.file_size for entry in entries) > MAX_EXPANDED_WORKBOOK_BYTES:
            raise ValueError("Expanded workbook exceeds the 16 MiB local limit.")
        expanded = 0
        for entry in entries:
            if entry.flag_bits & 1 or entry.compress_type not in (
                zipfile.ZIP_STORED,
                zipfile.ZIP_DEFLATED,
            ):
                raise ValueError("Encrypted or unsupported workbook archives are not accepted.")
            if entry.filename.lower().endswith("vbaproject.bin"):
                raise ValueError("Macro-enabled workbooks are not accepted.")
            with archive.open(entry) as file:
                while chunk := file.read(64 * 1024):
                    expanded += len(chunk)
                    if expanded > MAX_EXPANDED_WORKBOOK_BYTES:
                        raise ValueError("Expanded workbook exceeds the 16 MiB local limit.")


class EngineInputValidator:
    def validate(self, document: dict, contents: dict[str, bytes]) -> dict:
        check_exam, read_rubric = engine_functions()
        try:
            for kind in ("roster", "rubric"):
                check_workbook(contents[kind])
        except (ValueError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
            raise ApplicationError(
                "INVALID_WORKBOOK", "Upload valid bounded XLSX roster and rubric files."
            ) from error

        with tempfile.TemporaryDirectory(prefix="foundry-preflight-") as directory:
            root = Path(directory)
            paths = {"scans": "scans.pdf", "roster": "roster.xlsx", "rubric": "rubric.xlsx"}
            for kind, filename in paths.items():
                (root / filename).write_bytes(contents[kind])
            settings = document["settings"]
            config = {
                "exam": {
                    "name": document["title"],
                    "roster": paths["roster"],
                    "roster_sheet": settings.get("roster_sheet", "Roster"),
                    "scanned_pdf": paths["scans"],
                    "marking_scheme": paths["rubric"],
                    "output_dir": "output",
                },
                "layout": {
                    "pages_per_student": settings["pages_per_student"],
                    "same_layout_for_all": settings.get("same_layout_for_all", False),
                },
            }
            issues, summary = check_exam(config, root)
            if issues:
                raise ApplicationError(
                    "INVALID_INPUTS",
                    "Input preflight failed. Correct the files or layout and review again.",
                    details=issues,
                )
            if summary["pdf_pages"] > MAX_PDF_PAGES:
                raise ApplicationError("INPUT_LIMIT", "The local PDF limit is 200 pages.")
            try:
                questions = read_rubric(root / paths["rubric"])
            except Exception as error:
                raise ApplicationError(
                    "INVALID_RUBRIC", "The rubric must have valid standard questions and marks."
                ) from error
            total_marks = sum(question["marks"] for question in questions)
            if not math.isfinite(total_marks):
                raise ApplicationError("INVALID_RUBRIC", "The total rubric marks must be finite.")
        return {
            "engine_commit": ENGINE_COMMIT,
            "policy_version": 1,
            "summary": {
                **summary,
                "questions": len(questions),
                "total_marks": total_marks,
                "attendance_mode": "all_roster_students",
            },
        }
