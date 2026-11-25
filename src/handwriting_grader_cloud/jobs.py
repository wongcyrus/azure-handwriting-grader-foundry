import hashlib
from uuid import uuid4

from .auth import Principal
from .errors import ApplicationError
from .job_repository import JobRepository, job_integrity_error
from .models import OfflineValidationRequest
from .preflight import ENGINE_COMMIT
from .region_review import review_hash
from .service import snapshot, utc_now
from .workspace import ENGINE_INPUT_WORKSPACE, WorkspaceBridge

OFFLINE_STAGE = "validate_engine_inputs"


class OfflineJobControl:
    """Internal offline admission/dispatch records, not an executor or worker authenticator."""

    def __init__(self, bridge: WorkspaceBridge):
        self.bridge = bridge
        self.repository = bridge.service.repository
        self.jobs = JobRepository(self.repository)

    @staticmethod
    def _role(principal: Principal, role: str) -> None:
        if role not in principal.roles:
            raise ApplicationError("FORBIDDEN", f"The {role} role is required.", 403)

    def request_validation(
        self,
        principal: Principal,
        exam_id: str,
        expected: int,
        request: OfflineValidationRequest,
    ) -> dict:
        self.bridge.service.current(principal, exam_id, expected)
        if request.confirmed is not True:
            raise ApplicationError(
                "REQUEST_REQUIRED", "Explicit offline job confirmation is required."
            )
        manifest, digest = self.bridge.validated_checkpoint(
            principal, exam_id, expected, str(request.checkpoint_id)
        )
        if manifest["kind"] != ENGINE_INPUT_WORKSPACE:
            raise ApplicationError(
                "ENGINE_INPUTS_REQUIRED", "Prepare current engine inputs before job admission.", 409
            )
        intent = {
            "schema_version": 1,
            "id": str(uuid4()),
            "stage": OFFLINE_STAGE,
            "created_at": utc_now(),
            "request_id": str(request.request_id),
            "message_id": str(uuid4()),
            "checkpoint_id": str(request.checkpoint_id),
            "checkpoint_sha256": digest,
            "binding": manifest["binding"],
        }
        return self.jobs.admit(intent)

    def _current(self, job: dict) -> dict:
        if job["state"] == "CANCELLED":
            raise ApplicationError("JOB_CANCELLED", "This job has been cancelled.", 409)
        if job["outbox_hold"] is not None:
            raise ApplicationError("OUTBOX_HELD", "This pending job has an immutable hold.", 409)
        intent = job["intent"]
        try:
            if intent["schema_version"] != 1 or intent["stage"] != OFFLINE_STAGE:
                raise job_integrity_error()
            binding = intent["binding"]
            document = self.repository.get(binding["exam_id"])
            approvals = {
                "inputs": document["current_approval"],
                "regions": document["current_region_approval"],
            }
            if "attendance" in document["artifacts"]:
                approvals["attendance"] = document["current_attendance_approval"]
            if (
                document["state"] != "REGIONS_REVIEWED"
                or document["version"] != binding["exam_version"]
                or document["tenant_id"] != binding["tenant_id"]
                or document["owner_id"] != binding["owner_id"]
                or snapshot(document) != binding["snapshot_sha256"]
                or document["snapshot_sha256"] != binding["snapshot_sha256"]
                or review_hash(document["regions"]) != binding["regions_sha256"]
                or document["regions"]["review_sha256"] != binding["regions_sha256"]
                or approvals != binding["approval_ids"]
            ):
                raise ApplicationError(
                    "STALE_JOB", "The job no longer matches current approved inputs.", 409
                )
            checkpoint, digest = self.repository.checkpoint(
                binding["exam_id"], intent["checkpoint_id"]
            )
            if (
                digest != intent["checkpoint_sha256"]
                or checkpoint["binding"] != binding
                or checkpoint["kind"] != ENGINE_INPUT_WORKSPACE
                or checkpoint["engine_commit"] != ENGINE_COMMIT
            ):
                raise job_integrity_error()
        except (KeyError, ValueError, TypeError) as error:
            raise job_integrity_error() from error
        return checkpoint

    def owned_job(self, principal: Principal, exam_id: str, job_id: str) -> dict:
        self.bridge.service.owned(principal, exam_id)
        job = self.jobs.get(job_id)
        binding = job["intent"]["binding"]
        if (
            binding["exam_id"] != exam_id
            or binding["owner_id"] != principal.object_id
            or binding["tenant_id"] != principal.tenant_id
        ):
            raise ApplicationError("NOT_FOUND", "Offline job not found.", 404)
        return job

    def pending(self, principal: Principal, limit: int = 20) -> list[dict]:
        self._role(principal, "JobDispatcher")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ApplicationError("INVALID_LIMIT", "Use an outbox limit from 1 to 50.")
        return self.jobs.pending(principal.tenant_id, limit)

    def acknowledge_dispatch(
        self, principal: Principal, job_id: str, message_id: str, worker: Principal
    ) -> dict:
        self._role(principal, "JobDispatcher")
        self._role(worker, "StageWorker")
        job = self.jobs.get(job_id)
        if (
            job["intent"]["binding"]["tenant_id"] != principal.tenant_id
            or worker.tenant_id != principal.tenant_id
            or job["intent"]["message_id"] != message_id
        ):
            raise ApplicationError("NOT_FOUND", "Offline dispatch message not found.", 404)
        self._current(job)
        return self.jobs.acknowledge(job, worker.object_id, utc_now())

    def worker_context(self, principal: Principal, job_id: str, message_id: str) -> dict:
        self._role(principal, "StageWorker")
        job = self.jobs.get(job_id)
        if (
            job["intent"]["binding"]["tenant_id"] != principal.tenant_id
            or job["intent"]["message_id"] != message_id
            or job["worker_id"] != principal.object_id
        ):
            raise ApplicationError("NOT_FOUND", "No worker grant exists for this job.", 404)
        checkpoint = self._current(job)
        self.repository.assert_version(
            job["intent"]["binding"]["exam_id"], job["intent"]["binding"]["exam_version"]
        )
        return {
            "job_id": job_id,
            "message_id": message_id,
            "stage": OFFLINE_STAGE,
            "binding": job["intent"]["binding"],
            "checkpoint": checkpoint,
            "checkpoint_sha256": job["intent"]["checkpoint_sha256"],
            "intent_sha256": job["intent_sha256"],
        }

    def worker_artifact(
        self, principal: Principal, job_id: str, message_id: str, artifact_id: str
    ) -> bytes:
        context = self.worker_context(principal, job_id, message_id)
        references = [
            item
            for item in context["checkpoint"]["files"].values()
            if item["artifact_id"] == artifact_id
        ]
        if not references:
            raise ApplicationError("NOT_FOUND", "Artifact is outside the job grant.", 404)
        content = self.repository.content(context["binding"]["exam_id"], artifact_id)
        if any(
            len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]
            for item in references
        ):
            raise job_integrity_error()
        self.repository.assert_version(
            context["binding"]["exam_id"], context["binding"]["exam_version"]
        )
        return content
