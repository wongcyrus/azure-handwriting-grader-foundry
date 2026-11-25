from dataclasses import asdict
from uuid import UUID

from pydantic import ConfigDict, Field, StrictStr, ValidationError

from .auth import Principal
from .delivery import OfflineDispatcher, QueueMessage
from .errors import ApplicationError
from .execution import OfflineValidationExecutor
from .jobs import OFFLINE_STAGE, OfflineJobControl
from .models import StrictModel


class OfflineQueueEnvelope(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False, frozen=True)
    job_id: UUID
    message_id: UUID
    worker_id: StrictStr = Field(min_length=1, max_length=256)


class OfflineJobCoordinator:
    """One-shot synthetic consumption and owner inspection; no polling or HTTP authority."""

    def __init__(
        self,
        control: OfflineJobControl,
        dispatcher: OfflineDispatcher,
        executor: OfflineValidationExecutor,
    ):
        if dispatcher.control is not control or executor.control is not control:
            raise ValueError(
                "Use the same trusted control boundary for all coordinator components."
            )
        self.control = control
        self.dispatcher = dispatcher
        self.executor = executor

    def consume(
        self,
        principal: Principal,
        message: QueueMessage | dict | OfflineQueueEnvelope,
        attempt_id: UUID,
    ) -> dict:
        self.control._role(principal, "StageWorker")
        try:
            envelope = OfflineQueueEnvelope.model_validate(
                asdict(message) if isinstance(message, QueueMessage) else message
            )
        except ValidationError as error:
            raise ApplicationError(
                "INVALID_MESSAGE", "Use only the opaque offline queue envelope."
            ) from error
        if envelope.worker_id != principal.object_id:
            raise ApplicationError(
                "NOT_FOUND", "This envelope is not addressed to this worker.", 404
            )
        job_id, message_id = str(envelope.job_id), str(envelope.message_id)
        self.control.worker_context(principal, job_id, message_id)
        job = self.control.jobs.get(job_id)
        with self.control.repository.connection() as connection:
            delivery = self.dispatcher._load(connection, job)
        if (
            delivery is None
            or delivery["state"] != "DELIVERED"
            or delivery["worker_id"] != principal.object_id
        ):
            raise ApplicationError(
                "DELIVERY_REQUIRED",
                "Confirmed scoped delivery is required before consumption.",
                409,
            )
        return self.executor.run(principal, job_id, message_id, attempt_id)

    def owned_status(self, principal: Principal, exam_id: str, job_id: str) -> dict:
        observed = self.control.bridge.service.owned(principal, exam_id)
        job = self.control.owned_job(principal, exam_id, job_id)
        with self.control.repository.connection() as connection:
            delivery = self.dispatcher._load(connection, job)
        execution = job["execution"]
        current = True
        try:
            self.control._current(job)
        except ApplicationError as error:
            if error.code not in ("STALE_JOB", "JOB_CANCELLED", "OUTBOX_HELD"):
                raise
            current = False
        result_available = execution["state"] == "COMPLETED"
        if result_available:
            self.executor._result(job)
        now = self.executor._now()
        can_consume = False
        if execution["state"] == "CANCELLED":
            state = "CANCELLED"
        elif job["outbox_hold"] is not None:
            state = job["outbox_hold"]["state"]
        elif result_available:
            state = "VALIDATED" if current else "VALIDATED_HISTORICAL"
        elif not current:
            state = "STALE_INPUTS"
        elif execution["state"] in ("CLAIMED", "RUNNING"):
            expired = self.executor._expiry(execution) <= now
            state = "VALIDATION_CLAIM_EXPIRED" if expired else f"VALIDATION_{execution['state']}"
            can_consume = expired and delivery is not None and delivery["state"] == "DELIVERED"
        elif delivery is not None:
            if delivery["state"] == "DELIVERED":
                state, can_consume = "READY_FOR_VALIDATION", True
            elif delivery["state"] == "SENDING":
                expired = self.dispatcher._time(delivery["attempts"][-1]["expires_at"]) <= now
                state = "DELIVERY_SEND_EXPIRED" if expired else "DELIVERY_SENDING"
            elif delivery["state"] == "RETRY_WAIT":
                due = self.dispatcher._time(delivery["next_attempt_at"]) <= now
                state = "DELIVERY_RETRY_READY" if due else "DELIVERY_RETRY_WAIT"
            else:
                state = "DELIVERY_REVIEW"
        else:
            state = "PENDING_DISPATCH" if job["worker_id"] is None else "ASSIGNED_WITHOUT_DELIVERY"
        self.control.repository.assert_version(exam_id, observed["version"])
        return {
            "job_id": job_id,
            "exam_version": observed["version"],
            "source_exam_version": job["intent"]["binding"]["exam_version"],
            "message_id": job["intent"]["message_id"],
            "stage": OFFLINE_STAGE,
            "state": state,
            "current_job_scope": current,
            "eligible_for_validation": can_consume,
            "delivery_state": None if delivery is None else delivery["state"],
            "execution_state": execution["state"],
            "result_available": result_available,
            "result_sha256": execution.get("result_sha256"),
            "outbox_hold": job["outbox_hold"],
        }

    def owned_jobs(
        self, principal: Principal, exam_id: str, limit: int = 20, cursor: UUID | None = None
    ) -> dict:
        observed = self.control.bridge.service.owned(principal, exam_id)
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ApplicationError("INVALID_LIMIT", "Use a job limit from 1 to 50.")
        try:
            after = "" if cursor is None else str(UUID(str(cursor)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ApplicationError("INVALID_CURSOR", "Use an opaque UUID job cursor.") from error
        page = self.control.jobs.owned_ids(
            exam_id, principal.tenant_id, principal.object_id, limit, after
        )
        items = [self.owned_status(principal, exam_id, job_id) for job_id in page["job_ids"]]
        self.control.repository.assert_version(exam_id, observed["version"])
        return {
            "items": items,
            "next_cursor": page["next_cursor"],
            "exam_version": observed["version"],
        }

    def owned_result(self, principal: Principal, exam_id: str, job_id: str) -> dict:
        return self.executor.owned_result(principal, exam_id, job_id)
