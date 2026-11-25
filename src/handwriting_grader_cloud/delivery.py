import hashlib
import json
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import UUID, uuid4

from .auth import Principal
from .errors import ApplicationError
from .execution import CLAIM_DURATION
from .job_repository import job_integrity_error
from .jobs import OFFLINE_STAGE, OfflineJobControl

MAX_DELIVERY_ATTEMPTS = 3
RETRY_DELAYS = (timedelta(seconds=5), timedelta(seconds=30))


class DeliveryUnconfirmed(Exception):
    pass


@dataclass(frozen=True)
class QueueMessage:
    job_id: str
    message_id: str
    worker_id: str


class SimulatedQueue:
    """In-memory synthetic delivery only; faults may leave duplicate accepted messages."""

    def __init__(self, failures: tuple[str, ...] = ()):
        if any(failure not in ("not_accepted", "ack_lost") for failure in failures):
            raise ValueError("Use only simulated delivery failures.")
        self.failures = deque(failures)
        self.messages: list[QueueMessage] = []
        self.send_count = 0
        self.lock = Lock()

    def send(self, message: QueueMessage) -> str:
        with self.lock:
            self.send_count += 1
            failure = self.failures.popleft() if self.failures else None
            if failure == "not_accepted":
                raise DeliveryUnconfirmed("Synthetic send was not accepted.")
            self.messages.append(message)
            if failure == "ack_lost":
                raise DeliveryUnconfirmed("Synthetic acknowledgement was lost.")
            return str(uuid4())


class OfflineDispatcher:
    """Durable bounded send watermarks for a local simulated queue, not a consumer."""

    def __init__(
        self,
        control: OfflineJobControl,
        queue: SimulatedQueue,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.control = control
        self.repository = control.repository
        self.queue = queue
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("The server clock must return timezone-aware time.")
        return now.astimezone(UTC)

    @staticmethod
    def _time(value: str) -> datetime:
        try:
            timestamp = datetime.fromisoformat(value)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise job_integrity_error()
            return timestamp
        except (ValueError, TypeError) as error:
            raise job_integrity_error() from error

    def _load(self, connection, job: dict) -> dict | None:
        intent = job["intent"]
        row = connection.execute(
            "SELECT document, sha256 FROM offline_delivery_control WHERE job_id=?",
            (intent["id"],),
        ).fetchone()
        if row is None:
            return None
        try:
            document = json.loads(row[0])
            attempts = document["attempts"]
            if (
                hashlib.sha256(row[0].encode()).hexdigest() != row[1]
                or document["job_id"] != intent["id"]
                or document["message_id"] != intent["message_id"]
                or document["intent_sha256"] != job["intent_sha256"]
                or document["stage"] != OFFLINE_STAGE
                or document["state"] not in ("SENDING", "RETRY_WAIT", "DELIVERED", "EXHAUSTED")
                or not 1 <= len(attempts) <= MAX_DELIVERY_ATTEMPTS
                or [attempt["number"] for attempt in attempts] != list(range(1, len(attempts) + 1))
                or len({attempt["attempt_id"] for attempt in attempts}) != len(attempts)
            ):
                raise job_integrity_error()
            for attempt in attempts:
                UUID(attempt["attempt_id"])
                self._time(attempt["expires_at"])
            if document["state"] == "DELIVERED":
                UUID(document["receipt_id"])
                if (
                    attempts[-1]["state"] != "CONFIRMED"
                    or job["worker_id"] != document["worker_id"]
                ):
                    raise job_integrity_error()
            return document
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise job_integrity_error() from error

    @staticmethod
    def _save(connection, document: dict) -> None:
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "INSERT INTO offline_delivery_control VALUES (?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET document=excluded.document, sha256=excluded.sha256",
            (document["job_id"], encoded, hashlib.sha256(encoded.encode()).hexdigest()),
        )

    def _job(
        self, connection, principal: Principal, job_id: str, message_id: str, worker: Principal
    ) -> dict:
        job = self.control.jobs._decode(self.control.jobs._select(connection, "j.id=?", (job_id,)))
        if (
            job["intent"]["binding"]["tenant_id"] != principal.tenant_id
            or worker.tenant_id != principal.tenant_id
            or job["intent"]["message_id"] != message_id
        ):
            raise ApplicationError("NOT_FOUND", "Offline delivery message not found.", 404)
        return job

    def _review(self, connection, principal: Principal, document: dict) -> None:
        hold = {
            "schema_version": 1,
            "job_id": document["job_id"],
            "message_id": document["message_id"],
            "tenant_id": principal.tenant_id,
            "state": "DELIVERY_REVIEW",
            "reason_code": "DELIVERY_ATTEMPTS_EXHAUSTED",
            "recorded_at": self._now().isoformat(),
            "actor_id": principal.object_id,
        }
        encoded = json.dumps(hold, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "INSERT INTO offline_outbox_holds VALUES (?, ?, ?)",
            (hold["job_id"], encoded, hashlib.sha256(encoded.encode()).hexdigest()),
        )

    def _unconfirmed(
        self, connection, principal: Principal, document: dict, failed_at: datetime
    ) -> None:
        number = len(document["attempts"])
        document["state"] = "EXHAUSTED" if number == MAX_DELIVERY_ATTEMPTS else "RETRY_WAIT"
        document["next_attempt_at"] = (
            None
            if number == MAX_DELIVERY_ATTEMPTS
            else (failed_at + RETRY_DELAYS[number - 1]).isoformat()
        )
        if document["state"] == "EXHAUSTED":
            self._review(connection, principal, document)
        self._save(connection, document)

    def _begin(
        self, principal: Principal, job_id: str, message_id: str, worker: Principal, attempt_id: str
    ) -> tuple[dict, bool]:
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._job(connection, principal, job_id, message_id, worker)
            document = self._load(connection, job)
            if document is not None and document["worker_id"] != worker.object_id:
                raise ApplicationError(
                    "DISPATCH_CONFLICT", "Delivery already has a recipient.", 409
                )
            if document is not None and document["state"] == "EXHAUSTED":
                return document, False
            binding = job["intent"]["binding"]
            self.repository._assert_version(connection, binding["exam_id"], binding["exam_version"])
            self.control._current(job)
            if document is not None and document["state"] == "DELIVERED":
                return document, False
            if job["worker_id"] is not None:
                raise ApplicationError(
                    "DISPATCH_ALREADY_ASSIGNED", "Legacy assignment is not proof of delivery.", 409
                )
            now = self._now()
            if document is not None:
                if any(attempt["attempt_id"] == attempt_id for attempt in document["attempts"]):
                    return document, False
                if document["state"] == "SENDING":
                    expiry = self._time(document["attempts"][-1]["expires_at"])
                    if expiry > now:
                        raise ApplicationError(
                            "DELIVERY_IN_FLIGHT", "Another send attempt is live.", 409
                        )
                    document["attempts"][-1]["state"] = "EXPIRED"
                    self._unconfirmed(connection, principal, document, expiry)
                if document["state"] == "EXHAUSTED":
                    return document, False
                if self._time(document["next_attempt_at"]) > now:
                    return document, False
            else:
                document = {
                    "job_id": job_id,
                    "message_id": message_id,
                    "stage": OFFLINE_STAGE,
                    "intent_sha256": job["intent_sha256"],
                    "worker_id": worker.object_id,
                    "attempts": [],
                }
            document["attempts"].append(
                {
                    "number": len(document["attempts"]) + 1,
                    "attempt_id": attempt_id,
                    "dispatcher_id": principal.object_id,
                    "claimed_at": now.isoformat(),
                    "expires_at": (now + CLAIM_DURATION).isoformat(),
                    "state": "SENDING",
                }
            )
            document.update(state="SENDING", next_attempt_at=None, receipt_id=None)
            self._save(connection, document)
        return document, True

    def _finish(
        self,
        principal: Principal,
        job_id: str,
        message_id: str,
        worker: Principal,
        attempt_id: str,
        receipt: str | None,
    ) -> dict:
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._job(connection, principal, job_id, message_id, worker)
            binding = job["intent"]["binding"]
            self.repository._assert_version(connection, binding["exam_id"], binding["exam_version"])
            self.control._current(job)
            document = self._load(connection, job)
            if document is None:
                raise job_integrity_error()
            attempt = document["attempts"][-1]
            if (
                document["state"] != "SENDING"
                or attempt["attempt_id"] != attempt_id
                or attempt["dispatcher_id"] != principal.object_id
                or document["worker_id"] != worker.object_id
                or self._time(attempt["expires_at"]) <= self._now()
            ):
                raise ApplicationError(
                    "DELIVERY_CLAIM_LOST", "This send attempt is no longer live.", 409
                )
            if receipt is None:
                attempt["state"] = "UNCONFIRMED"
                attempt["reason_code"] = "DELIVERY_UNCONFIRMED"
                self._unconfirmed(connection, principal, document, self._now())
            else:
                if job["worker_id"] is not None:
                    raise ApplicationError(
                        "DISPATCH_CONFLICT", "Assignment changed during delivery.", 409
                    )
                confirmed_at = self._now()
                if self._time(attempt["expires_at"]) <= confirmed_at:
                    raise ApplicationError("DELIVERY_CLAIM_LOST", "The send claim expired.", 409)
                document.update(state="DELIVERED", receipt_id=str(UUID(receipt)))
                attempt["state"] = "CONFIRMED"
                connection.execute(
                    "UPDATE offline_job_outbox SET worker_id=?, dispatched_at=? WHERE job_id=?",
                    (worker.object_id, confirmed_at.isoformat(), job_id),
                )
                self._save(connection, document)
        return document

    def dispatch(
        self,
        principal: Principal,
        job_id: str,
        message_id: str,
        worker: Principal,
        attempt_id: UUID,
    ) -> dict:
        self.control._role(principal, "JobDispatcher")
        self.control._role(worker, "StageWorker")
        try:
            nonce = str(UUID(str(attempt_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ApplicationError("INVALID_ATTEMPT", "Use a unique send-attempt UUID.") from error
        document, acquired = self._begin(principal, job_id, message_id, worker, nonce)
        if not acquired:
            return document
        try:
            receipt = self.queue.send(QueueMessage(job_id, message_id, worker.object_id))
        except DeliveryUnconfirmed:
            receipt = None
        return self._finish(principal, job_id, message_id, worker, nonce, receipt)

    def status(self, principal: Principal, job_id: str) -> dict | None:
        self.control._role(principal, "JobDispatcher")
        job = self.control.jobs.get(job_id)
        if job["intent"]["binding"]["tenant_id"] != principal.tenant_id:
            raise ApplicationError("NOT_FOUND", "Offline delivery record not found.", 404)
        with self.repository.connection() as connection:
            return self._load(connection, job)
