import hashlib
import json

from .errors import ApplicationError
from .repository import SQLiteRepository


def job_integrity_error() -> ApplicationError:
    return ApplicationError("JOB_INTEGRITY", "Offline job control data is inconsistent.", 409)


class JobRepository:
    """Local control records only; no queue connection or execution lease."""

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
                """
            )

    @staticmethod
    def _decode(row) -> dict:
        if row is None:
            raise ApplicationError("NOT_FOUND", "Offline job not found.", 404)
        encoded, digest, message_id, worker_id, dispatched_at = row
        try:
            document = json.loads(encoded)
            if (
                hashlib.sha256(encoded.encode()).hexdigest() != digest
                or document["message_id"] != message_id
                or (worker_id is None) != (dispatched_at is None)
            ):
                raise job_integrity_error()
        except (ValueError, TypeError, KeyError) as error:
            raise job_integrity_error() from error
        return {
            "intent": document,
            "intent_sha256": digest,
            "state": "PENDING_DISPATCH" if worker_id is None else "DISPATCHED",
            "worker_id": worker_id,
            "dispatched_at": dispatched_at,
        }

    @staticmethod
    def _select(connection, where: str, parameters):
        return connection.execute(
            "SELECT j.document, j.sha256, o.message_id, o.worker_id, o.dispatched_at "
            "FROM offline_validation_jobs j JOIN offline_job_outbox o ON o.job_id=j.id "
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
        return self.get(document["id"])

    def pending(self, tenant_id: str, limit: int) -> list[dict]:
        with self.repository.connection() as connection:
            rows = connection.execute(
                "SELECT j.id, o.message_id FROM offline_validation_jobs j "
                "JOIN offline_job_outbox o ON o.job_id=j.id "
                "WHERE j.tenant_id=? AND o.worker_id IS NULL ORDER BY j.id LIMIT ?",
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
