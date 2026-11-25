import hashlib
import json
from uuid import UUID

from .auth import Principal
from .errors import ApplicationError
from .job_repository import decode_hold, job_integrity_error
from .jobs import OfflineJobControl
from .service import utc_now


class OutboxReconciler:
    """Bounded local dispatcher inspection; no delivery, retry loop or execution."""

    def __init__(self, control: OfflineJobControl):
        self.control = control
        self.repository = control.repository

    def _page(
        self, principal: Principal, limit: int, cursor: UUID | None, *, pending: bool
    ) -> tuple[list, str | None]:
        self.control._role(principal, "JobDispatcher")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ApplicationError("INVALID_LIMIT", "Use an outbox limit from 1 to 50.")
        try:
            after = "" if cursor is None else str(UUID(str(cursor)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ApplicationError("INVALID_CURSOR", "Use an opaque UUID outbox cursor.") from error
        condition = (
            "AND o.worker_id IS NULL AND h.job_id IS NULL "
            "AND CASE WHEN json_valid(e.document) "
            "THEN COALESCE(json_extract(e.document, '$.state'), 'INVALID') "
            "ELSE 'INVALID' END != 'CANCELLED' "
            if pending
            else ""
        )
        with self.repository.connection() as connection:
            rows = connection.execute(
                "SELECT j.id, o.message_id, o.worker_id, e.document, h.document, h.sha256 "
                "FROM offline_validation_jobs j "
                "JOIN offline_job_outbox o ON o.job_id=j.id "
                "LEFT JOIN offline_job_execution e ON e.job_id=j.id "
                "LEFT JOIN offline_outbox_holds h ON h.job_id=j.id "
                "WHERE j.tenant_id=? AND j.id>? " + condition + "ORDER BY j.id LIMIT ?",
                (principal.tenant_id, after, limit + 1),
            ).fetchall()
        return rows[:limit], rows[limit - 1][0] if len(rows) > limit else None

    def status(self, principal: Principal, limit: int = 20, cursor: UUID | None = None) -> dict:
        rows, next_cursor = self._page(principal, limit, cursor, pending=False)
        items = []
        for job_id, message_id, worker_id, execution_json, hold_json, hold_digest in rows:
            hold = decode_hold(hold_json, hold_digest, job_id, message_id, principal.tenant_id)
            state = "DISPATCHED" if worker_id is not None else "PENDING_DISPATCH"
            try:
                execution = json.loads(execution_json)
                if (
                    execution["state"]
                    not in ("READY", "CLAIMED", "RUNNING", "COMPLETED", "CANCELLED")
                    or type(execution["fence"]) is not int
                    or execution["fence"] < 0
                ):
                    raise ValueError("Invalid execution metadata.")
                if execution["state"] == "CANCELLED":
                    state = "CANCELLED"
            except (ValueError, TypeError, KeyError):
                state = "RECONCILIATION_REQUIRED"
            if hold is not None and state != "CANCELLED":
                state = hold["state"]
            items.append({"job_id": job_id, "message_id": message_id, "state": state, "hold": hold})
        return {"items": items, "next_cursor": next_cursor}

    def _reconcile_one(self, principal: Principal, job_id: str) -> str:
        with self.repository.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT o.message_id, o.worker_id, h.document, h.sha256 "
                "FROM offline_validation_jobs j "
                "JOIN offline_job_outbox o ON o.job_id=j.id "
                "LEFT JOIN offline_outbox_holds h ON h.job_id=j.id "
                "WHERE j.id=? AND j.tenant_id=?",
                (job_id, principal.tenant_id),
            ).fetchone()
            if row is None:
                raise ApplicationError("NOT_FOUND", "Offline outbox entry not found.", 404)
            message_id, worker_id, hold_json, hold_digest = row
            if worker_id is not None:
                return "SKIPPED"
            existing = decode_hold(hold_json, hold_digest, job_id, message_id, principal.tenant_id)
            if existing is not None:
                return existing["state"]
            try:
                job = self.control.jobs._decode(
                    self.control.jobs._select(connection, "j.id=?", (job_id,))
                )
                if job["state"] == "CANCELLED":
                    return "SKIPPED"
                if job["execution"]["state"] != "READY":
                    raise job_integrity_error()
                self.control._current(job)
                return "CURRENT"
            except ApplicationError as error:
                if error.code in ("STALE_JOB", "STALE_REVIEW"):
                    state, reason = "STALE", "STALE_JOB"
                elif error.code in ("JOB_INTEGRITY", "WORKSPACE_INTEGRITY", "NOT_FOUND"):
                    state, reason = "QUARANTINED", "JOB_INTEGRITY"
                else:
                    raise
            hold = {
                "schema_version": 1,
                "job_id": job_id,
                "message_id": message_id,
                "tenant_id": principal.tenant_id,
                "state": state,
                "reason_code": reason,
                "recorded_at": utc_now(),
                "actor_id": principal.object_id,
            }
            encoded = json.dumps(hold, sort_keys=True, separators=(",", ":"))
            connection.execute(
                "INSERT INTO offline_outbox_holds VALUES (?, ?, ?)",
                (job_id, encoded, hashlib.sha256(encoded.encode()).hexdigest()),
            )
        return state

    def reconcile_job(self, principal: Principal, job_id: UUID) -> dict:
        self.control._role(principal, "JobDispatcher")
        try:
            identifier = str(UUID(str(job_id)))
        except (ValueError, TypeError, AttributeError) as error:
            raise ApplicationError("INVALID_JOB", "Use an opaque UUID job identifier.") from error
        return {"job_id": identifier, "state": self._reconcile_one(principal, identifier)}

    def reconcile(self, principal: Principal, limit: int = 20, cursor: UUID | None = None) -> dict:
        rows, next_cursor = self._page(principal, limit, cursor, pending=True)
        outcomes = [
            {
                "job_id": row[0],
                "message_id": row[1],
                "state": self._reconcile_one(principal, row[0]),
            }
            for row in rows
        ]
        return {"items": outcomes, "next_cursor": next_cursor}
