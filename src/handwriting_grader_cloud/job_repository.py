import hashlib
import json

from .errors import ApplicationError
from .repository import SQLiteRepository


def job_integrity_error() -> ApplicationError:
    return ApplicationError("JOB_INTEGRITY", "Offline job control data is inconsistent.", 409)


def decode_hold(encoded, digest, job_id: str, message_id: str, tenant_id: str) -> dict | None:
    if encoded is None and digest is None:
        return None
    try:
        hold = json.loads(encoded)
        if (
            hashlib.sha256(encoded.encode()).hexdigest() != digest
            or hold["schema_version"] != 1
            or hold["job_id"] != job_id
            or hold["message_id"] != message_id
            or hold["tenant_id"] != tenant_id
            or (hold["state"], hold["reason_code"])
            not in (("STALE", "STALE_JOB"), ("QUARANTINED", "JOB_INTEGRITY"))
        ):
            raise job_integrity_error()
        return hold
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise job_integrity_error() from error


class JobRepository:
    """Local control records; no queue connection."""

    def __init__(self, repository: SQLiteRepository):
        self.repository = repository
        with repository.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS offline_validation_jobs (
                    id TEXT PRIMARY KEY,
                    exam_id TEXT NOT NULL REFERENCES exams(id),
                    tenant_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL REFERENCES workspace_checkpoints(id),
                    document TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    UNIQUE (exam_id, owner_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS offline_job_outbox (
                    job_id TEXT PRIMARY KEY REFERENCES offline_validation_jobs(id),
                    message_id TEXT UNIQUE NOT NULL,
                    worker_id TEXT,
                    dispatched_at TEXT
                );
                CREATE TABLE IF NOT EXISTS offline_job_execution (
                    job_id TEXT PRIMARY KEY REFERENCES offline_validation_jobs(id),
                    document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offline_validation_results (
                    job_id TEXT PRIMARY KEY REFERENCES offline_validation_jobs(id),
                    document TEXT NOT NULL,
                    sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offline_outbox_holds (
                    job_id TEXT PRIMARY KEY REFERENCES offline_validation_jobs(id),
                    document TEXT NOT NULL,
                    sha256 TEXT NOT NULL
                );
                INSERT OR IGNORE INTO offline_job_execution (job_id, document)
                    SELECT id, '{"state":"READY","fence":0}' FROM offline_validation_jobs;
                """
            )

    @staticmethod
    def _decode(row) -> dict:
        if row is None:
            raise ApplicationError("NOT_FOUND", "Offline job not found.", 404)
        (
            encoded,
            digest,
            message_id,
            worker_id,
            dispatched_at,
            execution_json,
            job_id,
            exam_id,
            tenant_id,
            owner_id,
            request_id,
            checkpoint_id,
            hold_json,
            hold_digest,
        ) = row
        try:
            document = json.loads(encoded)
            execution = json.loads(execution_json)
            hold = decode_hold(hold_json, hold_digest, job_id, message_id, tenant_id)
            if (
                hashlib.sha256(encoded.encode()).hexdigest() != digest
                or document["message_id"] != message_id
                or (worker_id is None) != (dispatched_at is None)
                or execution["state"]
                not in ("READY", "CLAIMED", "RUNNING", "COMPLETED", "CANCELLED")
                or type(execution["fence"]) is not int
                or execution["fence"] < 0
                or document["id"] != job_id
                or document["binding"]["exam_id"] != exam_id
                or document["binding"]["tenant_id"] != tenant_id
                or document["binding"]["owner_id"] != owner_id
                or document["request_id"] != request_id
                or document["checkpoint_id"] != checkpoint_id
            ):
                raise job_integrity_error()
        except (ValueError, TypeError, KeyError) as error:
            raise job_integrity_error() from error
        return {
            "intent": document,
            "intent_sha256": digest,
            "state": (
                execution["state"]
                if execution["state"] != "READY"
                else hold["state"]
                if hold is not None
                else "PENDING_DISPATCH"
                if worker_id is None
                else "DISPATCHED"
            ),
            "execution": execution,
            "outbox_hold": hold,
            "worker_id": worker_id,
            "dispatched_at": dispatched_at,
        }

    @staticmethod
    def _select(connection, where: str, parameters):
        return connection.execute(
            "SELECT j.document, j.sha256, o.message_id, o.worker_id, o.dispatched_at, e.document "
            ", j.id, j.exam_id, j.tenant_id, j.owner_id, j.request_id, j.checkpoint_id "
            ", h.document, h.sha256 "
            "FROM offline_validation_jobs j JOIN offline_job_outbox o ON o.job_id=j.id "
            "JOIN offline_job_execution e ON e.job_id=j.id "
            "LEFT JOIN offline_outbox_holds h ON h.job_id=j.id "
            f"WHERE {where}",
            parameters,
        ).fetchone()

    def get(self, job_id: str) -> dict:
        with self.repository.connection() as connection:
            return self._decode(self._select(connection, "j.id=?", (job_id,)))

    def admit(self, document: dict) -> dict:
        binding = document["binding"]
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._assert_version(connection, binding["exam_id"], binding["exam_version"])
            checkpoint = connection.execute(
                "SELECT manifest_sha256 FROM workspace_checkpoints WHERE exam_id=? AND id=?",
                (binding["exam_id"], document["checkpoint_id"]),
            ).fetchone()
            if checkpoint is None or checkpoint[0] != document["checkpoint_sha256"]:
                raise job_integrity_error()
            existing = self._select(
                connection,
                "j.exam_id=? AND j.owner_id=? AND j.request_id=?",
                (binding["exam_id"], binding["owner_id"], document["request_id"]),
            )
            if existing is not None:
                previous = self._decode(existing)
                if any(
                    previous["intent"][key] != document[key]
                    for key in (
                        "schema_version",
                        "stage",
                        "binding",
                        "request_id",
                        "checkpoint_id",
                        "checkpoint_sha256",
                    )
                ):
                    raise ApplicationError(
                        "REQUEST_CONFLICT", "This request ID already identifies another job.", 409
                    )
                return previous
            connection.execute(
                "INSERT INTO offline_validation_jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document["id"],
                    binding["exam_id"],
                    binding["tenant_id"],
                    binding["owner_id"],
                    document["request_id"],
                    document["checkpoint_id"],
                    encoded,
                    digest,
                ),
            )
            connection.execute(
                "INSERT INTO offline_job_outbox (job_id, message_id) VALUES (?, ?)",
                (document["id"], document["message_id"]),
            )
            connection.execute(
                "INSERT INTO offline_job_execution VALUES (?, ?)",
                (document["id"], '{"state":"READY","fence":0}'),
            )
        return self.get(document["id"])

    def pending(self, tenant_id: str, limit: int) -> list[dict]:
        with self.repository.connection() as connection:
            rows = connection.execute(
                "SELECT j.id, o.message_id FROM offline_validation_jobs j "
                "JOIN offline_job_outbox o ON o.job_id=j.id "
                "JOIN offline_job_execution e ON e.job_id=j.id "
                "WHERE j.tenant_id=? AND o.worker_id IS NULL "
                "AND CASE WHEN json_valid(e.document) "
                "THEN json_extract(e.document, '$.state') ELSE 'INVALID' END='READY' "
                "AND NOT EXISTS (SELECT 1 FROM offline_outbox_holds h WHERE h.job_id=j.id) "
                "ORDER BY j.id LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [{"job_id": job_id, "message_id": message_id} for job_id, message_id in rows]

    def acknowledge(self, job: dict, worker_id: str, dispatched_at: str) -> dict:
        intent = job["intent"]
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self.repository._assert_version(
                connection, intent["binding"]["exam_id"], intent["binding"]["exam_version"]
            )
            current = self._decode(self._select(connection, "j.id=?", (intent["id"],)))
            if current["intent_sha256"] != job["intent_sha256"]:
                raise job_integrity_error()
            if current["state"] == "CANCELLED":
                raise ApplicationError("JOB_CANCELLED", "This job has been cancelled.", 409)
            if current["outbox_hold"] is not None:
                raise ApplicationError(
                    "OUTBOX_HELD", "This pending job has an immutable hold.", 409
                )
            if current["worker_id"] is not None:
                if current["worker_id"] != worker_id:
                    raise ApplicationError(
                        "DISPATCH_CONFLICT", "This message already has a worker assignment.", 409
                    )
                return current
            connection.execute(
                "UPDATE offline_job_outbox SET worker_id=?, dispatched_at=? WHERE job_id=?",
                (worker_id, dispatched_at, intent["id"]),
            )
        return self.get(intent["id"])
