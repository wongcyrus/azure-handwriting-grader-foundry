import argparse
import json
from pathlib import Path
from uuid import UUID, uuid4

from .auth import DEVELOPMENT_TENANT_ID, Principal
from .coordinator import OfflineJobCoordinator, OfflineQueueEnvelope
from .delivery import OfflineDispatcher, SimulatedQueue
from .errors import ApplicationError
from .execution import OfflineValidationExecutor
from .jobs import OFFLINE_STAGE, OfflineJobControl
from .outbox import OutboxReconciler
from .repository import SQLiteRepository
from .service import ExamService
from .workspace import WorkspaceBridge

SYNTHETIC_DISPATCHER = Principal(
    DEVELOPMENT_TENANT_ID,
    "00000000-0000-0000-0000-000000000003",
    frozenset({"JobDispatcher"}),
)
SYNTHETIC_WORKER = Principal(
    DEVELOPMENT_TENANT_ID,
    "00000000-0000-0000-0000-000000000004",
    frozenset({"StageWorker"}),
)


def run_once(coordinator: OfflineJobCoordinator, job_id: UUID) -> dict:
    control = coordinator.control
    outcome = OutboxReconciler(control).reconcile_job(SYNTHETIC_DISPATCHER, job_id)
    response = {
        "job_id": outcome["job_id"],
        "stage": OFFLINE_STAGE,
        "state": outcome["state"],
        "delivery_sends": 0,
    }
    if outcome["state"] not in ("CURRENT", "SKIPPED"):
        return response
    job = control.jobs.get(outcome["job_id"])
    if job["state"] == "CANCELLED":
        response["state"] = "CANCELLED"
        return response
    queue = coordinator.dispatcher.queue
    before = queue.send_count
    delivery = coordinator.dispatcher.dispatch(
        SYNTHETIC_DISPATCHER,
        outcome["job_id"],
        job["intent"]["message_id"],
        SYNTHETIC_WORKER,
        uuid4(),
    )
    response.update(
        delivery_sends=queue.send_count - before,
        delivery_attempts=len(delivery["attempts"]),
        next_attempt_at=delivery["next_attempt_at"],
    )
    if delivery["state"] != "DELIVERED":
        response["state"] = (
            "DELIVERY_REVIEW" if delivery["state"] == "EXHAUSTED" else "DELIVERY_RETRY_WAIT"
        )
        return response
    # A fresh invocation has no queue buffer; consumption still checks protected delivery.
    envelope = OfflineQueueEnvelope(
        job_id=job_id,
        message_id=UUID(job["intent"]["message_id"]),
        worker_id=SYNTHETIC_WORKER.object_id,
    )
    result = coordinator.consume(SYNTHETIC_WORKER, envelope, uuid4())
    completed = control.jobs.get(outcome["job_id"])
    response.update(
        state="VALIDATED",
        result_sha256=completed["execution"]["result_sha256"],
        validated_at=result["validated_at"],
        summary={
            key: result["summary"][key]
            for key in ("students", "absent", "pdf_pages", "total_marks")
        },
    )
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Attempt one named synthetic offline check; no polling, sleeping or AI."
    )
    parser.add_argument(
        "--development", action="store_true", help="Required synthetic-only consent"
    )
    parser.add_argument("--database", type=Path, default=Path(".local/exams.sqlite3"))
    parser.add_argument("--job-id", type=UUID, required=True)
    args = parser.parse_args(argv)
    if not args.development:
        parser.error("--development is required; production operator identity is not implemented.")
    if not args.database.is_file() or args.database.is_symlink():
        parser.error("Use an existing, non-symlink local synthetic database.")
    try:
        service = ExamService(SQLiteRepository(args.database))
        root = args.database.parent / "offline-workspaces"
        control = OfflineJobControl(WorkspaceBridge(service, root / "inputs"))
        dispatcher = OfflineDispatcher(control, SimulatedQueue())
        executor = OfflineValidationExecutor(control, root / "validation")
        response = run_once(OfflineJobCoordinator(control, dispatcher, executor), args.job_id)
    except ApplicationError as error:
        print(json.dumps({"error": {"code": error.code}}))
        return 1
    except Exception:
        print(json.dumps({"error": {"code": "OFFLINE_OPERATOR_FAILED"}}))
        return 1
    print(json.dumps(response, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
