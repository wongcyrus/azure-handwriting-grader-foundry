import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import UUID

from .auth import Principal
from .errors import ApplicationError
from .job_repository import job_integrity_error
from .jobs import OFFLINE_STAGE, OfflineJobControl
from .preflight import ENGINE_COMMIT, EngineInputValidator, engine_functions
from .workspace import INPUT_PATHS, WorkspaceBridge

CLAIM_DURATION = timedelta(minutes=5)


class OfflineValidationExecutor:
    """Internal fenced, read-only execution; no queue or worker HTTP authentication."""

    def __init__(
        self,
        control: OfflineJobControl,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.control = control
        self.repository = control.repository
        self.workspace = WorkspaceBridge(control.bridge.service, root)
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("The server clock must return timezone-aware UTC time.")
        return now.astimezone(UTC)

    def _locked_job(self, connection, principal: Principal, context: dict) -> dict:
        job = self.control.jobs._decode(
            self.control.jobs._select(connection, "j.id=?", (context["job_id"],))
        )
        if (
            job["intent_sha256"] != context["intent_sha256"]
            or job["worker_id"] != principal.object_id
            or job["intent"]["binding"]["tenant_id"] != principal.tenant_id
            or job["intent"]["message_id"] != context["message_id"]
        ):
            raise job_integrity_error()
        binding = context["binding"]
        self.repository._assert_version(connection, binding["exam_id"], binding["exam_version"])
        self.control._current(job)
        return job

    @staticmethod
    def _save(connection, job_id: str, execution: dict) -> None:
        connection.execute(
            "UPDATE offline_job_execution SET document=? WHERE job_id=?",
            (json.dumps(execution, sort_keys=True, separators=(",", ":")), job_id),
        )

    def claim(self, principal: Principal, job_id: str, message_id: str, attempt_id: UUID) -> dict:
        try:
            attempt = str(UUID(str(attempt_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ApplicationError(
                "INVALID_ATTEMPT", "Use a unique UUID for each worker attempt."
            ) from error
        context = self.control.worker_context(principal, job_id, message_id)
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._locked_job(connection, principal, context)["execution"]
            now = self._now()
            if execution["state"] == "COMPLETED":
                return execution
            if execution["state"] in ("CLAIMED", "RUNNING"):
                if self._expiry(execution) > now:
                    if execution["attempt_id"] == attempt:
                        return execution
                    raise ApplicationError(
                        "JOB_CLAIMED", "Another attempt holds a live claim.", 409
                    )
            execution = {
                "state": "CLAIMED",
                "fence": execution["fence"] + 1,
                "attempt_id": attempt,
                "expires_at": (now + CLAIM_DURATION).isoformat(),
            }
            self._save(connection, job_id, execution)
        return execution

    @staticmethod
    def _expiry(execution: dict) -> datetime:
        try:
            expiry = datetime.fromisoformat(execution["expires_at"])
            if expiry.tzinfo is None or expiry.utcoffset() is None:
                raise job_integrity_error()
            return expiry
        except (KeyError, TypeError, ValueError) as error:
            raise job_integrity_error() from error

    def _lease(self, connection, principal: Principal, context: dict, claim: dict) -> dict:
        execution = self._locked_job(connection, principal, context)["execution"]
        if (
            execution["state"] not in ("CLAIMED", "RUNNING")
            or any(
                execution.get(key) != claim.get(key)
                for key in ("fence", "attempt_id", "expires_at")
            )
            or self._expiry(execution) <= self._now()
        ):
            raise ApplicationError("CLAIM_LOST", "This attempt no longer has a live claim.", 409)
        return execution

    def _begin(self, principal: Principal, context: dict, claim: dict) -> None:
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            execution = self._lease(connection, principal, context, claim)
            if execution["state"] != "CLAIMED":
                raise ApplicationError(
                    "JOB_RUNNING", "This attempt already started execution.", 409
                )
            self._save(connection, context["job_id"], {**execution, "state": "RUNNING"})

    def cancel(self, principal: Principal, exam_id: str, job_id: str) -> dict:
        self.control.owned_job(principal, exam_id, job_id)
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self.control.jobs._decode(
                self.control.jobs._select(connection, "j.id=?", (job_id,))
            )
            document = json.loads(
                connection.execute("SELECT document FROM exams WHERE id=?", (exam_id,)).fetchone()[
                    0
                ]
            )
            if (
                document["owner_id"] != principal.object_id
                or document["tenant_id"] != principal.tenant_id
                or job["intent"]["binding"]["exam_id"] != exam_id
                or job["intent"]["binding"]["owner_id"] != principal.object_id
                or job["intent"]["binding"]["tenant_id"] != principal.tenant_id
            ):
                raise ApplicationError("NOT_FOUND", "Offline job not found.", 404)
            execution = job["execution"]
            if execution["state"] == "COMPLETED":
                raise ApplicationError(
                    "JOB_COMPLETED", "Completed results cannot be cancelled.", 409
                )
            if execution["state"] != "CANCELLED":
                self._save(
                    connection,
                    job_id,
                    {
                        **execution,
                        "state": "CANCELLED",
                        "fence": execution["fence"] + 1,
                        "cancelled_at": self._now().isoformat(),
                        "cancelled_by": principal.object_id,
                    },
                )
        return self.control.owned_job(principal, exam_id, job_id)

    def _result(self, job: dict) -> dict:
        with self.repository.connection() as connection:
            row = connection.execute(
                "SELECT document, sha256 FROM offline_validation_results WHERE job_id=?",
                (job["intent"]["id"],),
            ).fetchone()
        if (
            job["execution"]["state"] != "COMPLETED"
            or row is None
            or hashlib.sha256(row[0].encode()).hexdigest() != row[1]
            or job["execution"].get("result_sha256") != row[1]
        ):
            raise job_integrity_error()
        try:
            result = json.loads(row[0])
            if (
                result["job_id"] != job["intent"]["id"]
                or result["stage"] != OFFLINE_STAGE
                or result["checkpoint_sha256"] != job["intent"]["checkpoint_sha256"]
                or result["binding"] != job["intent"]["binding"]
                or result["engine_commit"] != ENGINE_COMMIT
                or result["status"] != "passed"
            ):
                raise job_integrity_error()
            return result
        except (ValueError, TypeError, KeyError) as error:
            raise job_integrity_error() from error

    def owned_result(self, principal: Principal, exam_id: str, job_id: str) -> dict:
        return self._result(self.control.owned_job(principal, exam_id, job_id))

    def _finish(self, principal: Principal, context: dict, claim: dict, result: dict) -> dict:
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._locked_job(connection, principal, context)
            if job["execution"]["state"] == "COMPLETED":
                if any(
                    job["execution"].get(key) != claim.get(key) for key in ("fence", "attempt_id")
                ):
                    raise ApplicationError(
                        "CLAIM_LOST", "A replacement attempt completed this job.", 409
                    )
                return self._result(job)
            execution = self._lease(connection, principal, context, claim)
            if execution["state"] != "RUNNING":
                raise ApplicationError("JOB_NOT_RUNNING", "Start the claimed attempt first.", 409)
            connection.execute(
                "INSERT INTO offline_validation_results VALUES (?, ?, ?)",
                (context["job_id"], encoded, digest),
            )
            completed_at = self._now()
            if self._expiry(execution) <= completed_at:
                raise ApplicationError("CLAIM_LOST", "This attempt's claim expired.", 409)
            self._save(
                connection,
                context["job_id"],
                {
                    **execution,
                    "state": "COMPLETED",
                    "completed_at": completed_at.isoformat(),
                    "result_sha256": digest,
                },
            )
        return result

    def run(self, principal: Principal, job_id: str, message_id: str, attempt_id: UUID) -> dict:
        claim = self.claim(principal, job_id, message_id, attempt_id)
        context = self.control.worker_context(principal, job_id, message_id)
        if claim["state"] == "COMPLETED":
            return self._result(self.control.jobs.get(job_id))
        self._begin(principal, context, claim)
        target = None
        try:
            files = {}
            for name, reference in context["checkpoint"]["files"].items():
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    raise job_integrity_error()
                with self.repository.connection() as connection:
                    self._lease(connection, principal, context, claim)
                files[name] = self.control.worker_artifact(
                    principal, job_id, message_id, reference["artifact_id"]
                )
            with self.repository.connection() as connection:
                self._lease(connection, principal, context, claim)
            target = self.workspace._write(files, engine_inputs=True)
            document = self.repository.get(context["binding"]["exam_id"])
            contents = {kind: files[path] for kind, path in INPUT_PATHS.items() if path in files}
            preflight = EngineInputValidator().validate(document, contents)
            engine_functions()
            result = {
                "schema_version": 1,
                "job_id": job_id,
                "stage": OFFLINE_STAGE,
                "checkpoint_sha256": context["checkpoint_sha256"],
                "binding": context["binding"],
                "engine_commit": ENGINE_COMMIT,
                "status": "passed",
                "summary": preflight["summary"],
                "validated_at": self._now().isoformat(),
            }
            return self._finish(principal, context, claim, result)
        finally:
            if target is not None:
                shutil.rmtree(target)
