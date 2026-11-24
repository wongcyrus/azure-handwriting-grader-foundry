import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from .auth import Principal
from .errors import ApplicationError
from .models import ArtifactKind, CreateExam, ReviewApproval
from .preflight import EngineInputValidator, InputValidator
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
            "preflight": None,
            "history": [],
        }
        document["snapshot_sha256"] = snapshot(document)
        self.repository.create(document)
        return document

    def save(self, document: dict, expected: int, artifact=None) -> dict:
        document["version"] = expected + 1
        document["snapshot_sha256"] = snapshot(document)
        self.repository.save(document, expected, artifact)
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
        document["preflight"] = None
        self.record(document, principal, f"uploaded_{kind}")
        return self.save(document, expected, (artifact_id, content))

    def settings(self, principal: Principal, exam_id: str, expected: int, settings: dict) -> dict:
        document = self.current(principal, exam_id, expected)
        document["settings"] = settings
        document["input_revision"] += 1
        document["state"] = "SETUP"
        document["current_approval"] = None
        document["preflight"] = None
        self.record(document, principal, "updated_settings")
        return self.save(document, expected)

    def request_review(self, principal: Principal, exam_id: str, expected: int) -> dict:
        document = self.current(principal, exam_id, expected)
        if document["state"] != "SETUP":
            raise ApplicationError("INVALID_STATE", "Only setup inputs can enter review.", 409)
        if set(document["artifacts"]) != {"scans", "roster", "rubric"}:
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
        document["state"] = "INPUTS_REVIEWED"
        self.record(document, principal, "approved_input_review")
        return self.save(document, expected)

    def validate_inputs(self, document: dict) -> dict:
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
        validated = self.validator.validate(document, contents)
        return {**validated, "snapshot_sha256": snapshot(document), "validated_at": utc_now()}

    def content(self, principal: Principal, exam_id: str, artifact_id: str) -> bytes:
        self.owned(principal, exam_id)
        return self.repository.content(exam_id, artifact_id)
