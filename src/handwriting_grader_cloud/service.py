import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from .auth import Principal
from .errors import ApplicationError
from .models import ArtifactKind, CreateExam, RegionApproval, RegionDraft, ReviewApproval
from .preflight import ENGINE_COMMIT, EngineInputValidator, InputValidator
from .region_review import render_template, review_hash, validate_regions
from .repository import SQLiteRepository


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def snapshot(document: dict) -> str:
    payload = {
        "exam_id": document["id"],
        "input_revision": document["input_revision"],
        "settings": document["settings"],
        "artifacts": document["artifacts"],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class ExamService:
    def __init__(self, repository: SQLiteRepository, validator: InputValidator | None = None):
        self.repository = repository
        self.validator = validator if validator is not None else EngineInputValidator()

    def require_teacher(self, principal: Principal) -> None:
        if "Teacher" not in principal.roles:
            raise ApplicationError("FORBIDDEN", "The Teacher role is required.", 403)

    def list_owned(self, principal: Principal, limit: int, cursor: str = "") -> dict:
        self.require_teacher(principal)
        return self.repository.list_owned(principal.tenant_id, principal.object_id, limit, cursor)

    def owned(self, principal: Principal, exam_id: str) -> dict:
        self.require_teacher(principal)
        document = self.repository.get(exam_id)
        if (
            document["tenant_id"] != principal.tenant_id
            or document["owner_id"] != principal.object_id
        ):
            raise ApplicationError("NOT_FOUND", "Exam not found.", 404)
        return document

    def current(self, principal: Principal, exam_id: str, expected_version: int) -> dict:
        document = self.owned(principal, exam_id)
        if document["version"] != expected_version:
            raise ApplicationError("STALE_REVIEW", "Refresh and review the current exam.", 409)
        return document

    def create(self, principal: Principal, request: CreateExam) -> dict:
        self.require_teacher(principal)
        document = {
            "schema_version": 1,
            "id": str(uuid4()),
            "tenant_id": principal.tenant_id,
            "owner_id": principal.object_id,
            "title": request.title,
            "settings": request.settings.model_dump(),
            "version": 1,
            "input_revision": 1,
            "state": "SETUP",
            "artifacts": {},
            "approvals": [],
            "current_approval": None,
            "current_attendance_approval": None,
            "preflight": None,
            "regions": None,
            "current_region_approval": None,
            "history": [],
        }
        document["snapshot_sha256"] = snapshot(document)
        self.repository.create(document)
        return document

    def save(self, document: dict, expected: int, artifact=None, artifacts=None) -> dict:
        document["version"] = expected + 1
        document["snapshot_sha256"] = snapshot(document)
        self.repository.save(document, expected, artifact, artifacts)
        return document

    def record(self, document: dict, principal: Principal, action: str) -> None:
        document["history"].append(
            {
                "action": action,
                "actor_id": principal.object_id,
                "tenant_id": principal.tenant_id,
                "at": utc_now(),
                "input_revision": document["input_revision"],
            }
        )

    def attach(
        self,
        principal: Principal,
        exam_id: str,
        expected: int,
        kind: ArtifactKind,
        content: bytes,
    ) -> dict:
        document = self.current(principal, exam_id, expected)
        if not content:
            raise ApplicationError("EMPTY_ARTIFACT", "An input file cannot be empty.")
        artifact_id = str(uuid4())
        document["artifacts"][kind] = {
            "id": artifact_id,
            "kind": kind,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        document["input_revision"] += 1
        document["state"] = "SETUP"
        document["current_approval"] = None
        document["current_attendance_approval"] = None
        document["preflight"] = None
        document["regions"] = None
        document["current_region_approval"] = None
        self.record(document, principal, f"uploaded_{kind}")
        return self.save(document, expected, (artifact_id, content))

    def settings(self, principal: Principal, exam_id: str, expected: int, settings: dict) -> dict:
        document = self.current(principal, exam_id, expected)
        document["settings"] = settings
        document["input_revision"] += 1
        document["state"] = "SETUP"
        document["current_approval"] = None
        document["current_attendance_approval"] = None
        document["preflight"] = None
        document["regions"] = None
        document["current_region_approval"] = None
        self.record(document, principal, "updated_settings")
        return self.save(document, expected)

    def request_review(self, principal: Principal, exam_id: str, expected: int) -> dict:
        document = self.current(principal, exam_id, expected)
        if document["state"] != "SETUP":
            raise ApplicationError("INVALID_STATE", "Only setup inputs can enter review.", 409)
        if not {"scans", "roster", "rubric"}.issubset(document["artifacts"]):
            raise ApplicationError("MISSING_INPUTS", "Upload scans, a roster and a rubric first.")
        if (
            not document["settings"]["scan_order_confirmed"]
            or document["settings"].get("same_layout_for_all") is not True
        ):
            raise ApplicationError(
                "LAYOUT_CONFIRMATION_REQUIRED", "Confirm scan order and the common page layout."
            )
        document["preflight"] = self.validate_inputs(document)
        document["state"] = "WAITING_FOR_INPUT_REVIEW"
        self.record(document, principal, "requested_input_review")
        return self.save(document, expected)

    def approve(
        self,
        principal: Principal,
        exam_id: str,
        expected: int,
        request: ReviewApproval,
    ) -> dict:
        document = self.current(principal, exam_id, expected)
        if document["state"] != "WAITING_FOR_INPUT_REVIEW":
            raise ApplicationError("INVALID_STATE", "This exam is not awaiting input review.", 409)
        if request.confirmed is not True:
            raise ApplicationError("APPROVAL_REQUIRED", "Explicit confirmation is required.")
        has_attendance = "attendance" in document["artifacts"]
        if has_attendance and request.attendance_confirmed is not True:
            raise ApplicationError(
                "ATTENDANCE_APPROVAL_REQUIRED",
                "Explicitly confirm the reviewed present/absent attendance list.",
            )
        if request.snapshot_sha256 != snapshot(document):
            raise ApplicationError("STALE_REVIEW", "The reviewed snapshot is not current.", 409)
        if (
            not isinstance(document.get("preflight"), dict)
            or document["preflight"].get("snapshot_sha256") != request.snapshot_sha256
        ):
            raise ApplicationError(
                "PREFLIGHT_REQUIRED", "Run input preflight before approval.", 409
            )
        document["preflight"] = self.validate_inputs(document)
        approval = {
            "id": str(uuid4()),
            "kind": "input_review_attestation",
            "actor_id": principal.object_id,
            "tenant_id": principal.tenant_id,
            "at": utc_now(),
            "snapshot_sha256": request.snapshot_sha256,
            "input_revision": document["input_revision"],
            "preflight_engine_commit": document["preflight"]["engine_commit"],
            "preflight_policy_version": document["preflight"]["policy_version"],
        }
        document["approvals"].append(approval)
        document["current_approval"] = approval["id"]
        document["current_attendance_approval"] = None
        if has_attendance:
            attendance_approval = {
                **approval,
                "id": str(uuid4()),
                "kind": "attendance_review_attestation",
                "attendance_sha256": document["artifacts"]["attendance"]["sha256"],
                "roster_sha256": document["artifacts"]["roster"]["sha256"],
            }
            document["approvals"].append(attendance_approval)
            document["current_attendance_approval"] = attendance_approval["id"]
            self.record(document, principal, "approved_attendance_review")
        document["state"] = "INPUTS_REVIEWED"
        self.record(document, principal, "approved_input_review")
        return self.save(document, expected)

    def input_contents(self, document: dict) -> dict[str, bytes]:
        contents = {}
        for kind, artifact in document["artifacts"].items():
            content = self.repository.content(document["id"], artifact["id"])
            if (
                len(content) != artifact["size"]
                or hashlib.sha256(content).hexdigest() != artifact["sha256"]
            ):
                raise ApplicationError(
                    "ARTIFACT_INTEGRITY", "Stored inputs no longer match their snapshot.", 409
                )
            contents[kind] = content
        return contents

    def validate_inputs(self, document: dict) -> dict:
        contents = self.input_contents(document)
        validated = self.validator.validate(document, contents)
        return {**validated, "snapshot_sha256": snapshot(document), "validated_at": utc_now()}

    def prepare_regions(self, principal: Principal, exam_id: str, expected: int) -> dict:
        document = self.current(principal, exam_id, expected)
        if document["state"] != "INPUTS_REVIEWED":
            raise ApplicationError(
                "INVALID_STATE", "Approve inputs before region preparation.", 409
            )
        if not any(
            approval["id"] == document["current_approval"]
            and approval["kind"] == "input_review_attestation"
            and approval["snapshot_sha256"] == snapshot(document)
            for approval in document["approvals"]
        ):
            raise ApplicationError(
                "INPUT_APPROVAL_REQUIRED", "Current input approval is required.", 409
            )
        document["preflight"] = self.validate_inputs(document)
        regions, artifacts = render_template(document, self.input_contents(document)["scans"])
        document["regions"] = regions
        document["current_region_approval"] = None
        document["state"] = "WAITING_FOR_REGION_REVIEW"
        self.record(document, principal, "prepared_regions")
        return self.save(document, expected, artifacts=artifacts)

    def region_document(
        self, principal: Principal, exam_id: str, expected: int | None = None
    ) -> dict:
        document = (
            self.owned(principal, exam_id)
            if expected is None
            else self.current(principal, exam_id, expected)
        )
        regions = document.get("regions")
        if (
            not isinstance(regions, dict)
            or regions.get("snapshot_sha256") != snapshot(document)
            or regions.get("engine_commit") != ENGINE_COMMIT
            or regions.get("policy_version") != 1
            or regions.get("source_pdf_sha256") != document["artifacts"]["scans"]["sha256"]
            or regions.get("review_sha256") != review_hash(regions)
        ):
            raise ApplicationError(
                "REGIONS_REQUIRED", "Prepare regions for the current inputs.", 409
            )
        self.input_contents(document)
        validate_regions(regions)
        for page in regions["pages"]:
            content = self.repository.content(exam_id, page["artifact_id"])
            if hashlib.sha256(content).hexdigest() != page["sha256"]:
                raise ApplicationError(
                    "ARTIFACT_INTEGRITY", "Rendered page no longer matches review.", 409
                )
        return document

    def region_page(self, principal: Principal, exam_id: str, page_index: int) -> bytes:
        document = self.region_document(principal, exam_id)
        pages = document["regions"]["pages"]
        if not 0 <= page_index < len(pages):
            raise ApplicationError("NOT_FOUND", "Template page not found.", 404)
        return self.repository.content(exam_id, pages[page_index]["artifact_id"])

    def save_regions(
        self, principal: Principal, exam_id: str, expected: int, request: RegionDraft
    ) -> dict:
        document = self.region_document(principal, exam_id, expected)
        if document["state"] not in {"WAITING_FOR_REGION_REVIEW", "REGIONS_REVIEWED"}:
            raise ApplicationError("INVALID_STATE", "This exam is not in region review.", 409)
        if request.snapshot_sha256 != snapshot(document):
            raise ApplicationError("STALE_REVIEW", "The input snapshot changed.", 409)
        regions = document["regions"]
        regions["annotations"] = {
            key: [box.model_dump() for box in boxes] for key, boxes in request.annotations.items()
        }
        regions["reviewed_pages"] = request.reviewed_pages
        regions["revision"] += 1
        validate_regions(regions)
        regions["review_sha256"] = review_hash(regions)
        document["current_region_approval"] = None
        document["state"] = "WAITING_FOR_REGION_REVIEW"
        self.record(document, principal, "updated_region_draft")
        return self.save(document, expected)

    def approve_regions(
        self, principal: Principal, exam_id: str, expected: int, request: RegionApproval
    ) -> dict:
        document = self.region_document(principal, exam_id, expected)
        if document["state"] != "WAITING_FOR_REGION_REVIEW":
            raise ApplicationError(
                "INVALID_STATE", "This exam is not awaiting region approval.", 409
            )
        if request.confirmed is not True:
            raise ApplicationError("APPROVAL_REQUIRED", "Explicit confirmation is required.")
        if (
            request.snapshot_sha256 != snapshot(document)
            or request.regions_sha256 != document["regions"]["review_sha256"]
        ):
            raise ApplicationError("STALE_REVIEW", "The reviewed regions are not current.", 409)
        document["preflight"] = self.validate_inputs(document)
        if document["preflight"]["question_labels"] != document["regions"]["question_labels"]:
            raise ApplicationError("STALE_REVIEW", "The reviewed rubric changed.", 409)
        validate_regions(document["regions"], complete=True)
        approval = {
            "id": str(uuid4()),
            "kind": "regions_review_attestation",
            "actor_id": principal.object_id,
            "tenant_id": principal.tenant_id,
            "at": utc_now(),
            "snapshot_sha256": request.snapshot_sha256,
            "regions_sha256": request.regions_sha256,
            "preflight_engine_commit": document["preflight"]["engine_commit"],
            "region_policy_version": document["regions"]["policy_version"],
            "reviewed_regions": deepcopy(document["regions"]),
        }
        document["approvals"].append(approval)
        document["current_region_approval"] = approval["id"]
        document["state"] = "REGIONS_REVIEWED"
        self.record(document, principal, "approved_region_review")
        return self.save(document, expected)

    def content(self, principal: Principal, exam_id: str, artifact_id: str) -> bytes:
        self.owned(principal, exam_id)
        return self.repository.content(exam_id, artifact_id)
