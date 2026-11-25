import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from conftest import ADMIN, TEACHER, WORKER
from test_jobs import DISPATCHER, OTHER_DISPATCHER, dispatch
from test_workspace import approved_review

from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.execution import OfflineValidationExecutor
from handwriting_grader_cloud.jobs import OfflineJobControl
from handwriting_grader_cloud.models import OfflineValidationRequest
from handwriting_grader_cloud.outbox import OutboxReconciler
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService
from handwriting_grader_cloud.workspace import WorkspaceBridge

pytestmark = pytest.mark.engine


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    from handwriting_grader import attendance, grading, regions, rubric

    def forbidden(*_args, **_kwargs):
        pytest.fail("Outbox inspection/reconciliation must not execute a job.")

    monkeypatch.setattr(grading, "grade_exam", forbidden)
    monkeypatch.setattr(attendance, "approve_attendance", forbidden)
    monkeypatch.setattr(rubric, "approve_rubric", forbidden)
    monkeypatch.setattr(regions, "approve_regions", forbidden)
    monkeypatch.setattr(OfflineValidationExecutor, "run", forbidden)


@pytest.fixture
def outbox_setup(client, service, tmp_path):
    document = approved_review(client).json()
    bridge = WorkspaceBridge(service, tmp_path / "review")
    workspace = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    control = OfflineJobControl(bridge)
    request = OfflineValidationRequest(
        checkpoint_id=workspace.checkpoint_id, request_id=uuid4(), confirmed=True
    )
    job = control.request_validation(TEACHER, document["id"], document["version"], request)
    return SimpleNamespace(
        document=document,
        control=control,
        request=request,
        job=job,
        job_id=job["intent"]["id"],
        outbox=OutboxReconciler(control),
        executor=OfflineValidationExecutor(control, tmp_path / "execution"),
    )


def hold_count(setup):
    with setup.control.repository.connection() as connection:
        return connection.execute("SELECT count(*) FROM offline_outbox_holds").fetchone()[0]


def stored_intent(setup, job_id=None):
    with setup.control.repository.connection() as connection:
        return connection.execute(
            "SELECT document, sha256 FROM offline_validation_jobs WHERE id=?",
            (job_id or setup.job_id,),
        ).fetchone()


def change_inputs(setup):
    document = setup.document
    return setup.control.bridge.service.settings(
        TEACHER, document["id"], document["version"], document["settings"]
    )


def rewrite_intent(setup, intent, job_id=None):
    encoded = json.dumps(intent, sort_keys=True, separators=(",", ":"))
    with setup.control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_validation_jobs SET document=?, sha256=? WHERE id=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest(), job_id or setup.job_id),
        )


def test_current_pending_metadata_stays_eligible_without_execution_or_authority_changes(
    outbox_setup,
):
    setup = outbox_setup
    before = stored_intent(setup)
    report = setup.outbox.reconcile(DISPATCHER)
    assert report == {
        "items": [
            {
                "job_id": setup.job_id,
                "message_id": setup.job["intent"]["message_id"],
                "state": "CURRENT",
            }
        ],
        "next_cursor": None,
    }
    assert setup.outbox.status(DISPATCHER)["items"] == [
        {
            "job_id": setup.job_id,
            "message_id": setup.job["intent"]["message_id"],
            "state": "PENDING_DISPATCH",
            "hold": None,
        }
    ]
    assert stored_intent(setup) == before
    assert setup.control.repository.get(setup.document["id"]) == setup.document
    assert setup.control.jobs.get(setup.job_id) == setup.job
    assert len(setup.control.pending(DISPATCHER)) == 1
    assert hold_count(setup) == 0
    assert not setup.executor.workspace.root.exists()


def test_stale_pending_job_has_immutable_hold_surviving_restart(outbox_setup, tmp_path):
    setup = outbox_setup
    original = stored_intent(setup)
    updated = change_inputs(setup)
    assert setup.outbox.reconcile(DISPATCHER)["items"][0]["state"] == "STALE"
    hold = setup.control.jobs.get(setup.job_id)["outbox_hold"]
    assert hold["actor_id"] == DISPATCHER.object_id
    assert hold["tenant_id"] == DISPATCHER.tenant_id
    assert hold["reason_code"] == "STALE_JOB"
    assert setup.control.pending(DISPATCHER) == []
    assert setup.outbox.reconcile(DISPATCHER)["items"] == []
    assert stored_intent(setup) == original
    assert setup.control.repository.get(setup.document["id"]) == updated
    with pytest.raises(ApplicationError) as error:
        dispatch(setup.control, setup.job)
    assert error.value.code == "OUTBOX_HELD"
    restarted = OutboxReconciler(
        OfflineJobControl(
            WorkspaceBridge(
                ExamService(SQLiteRepository(setup.control.repository.path)), tmp_path / "restarted"
            )
        )
    )
    assert restarted.status(DISPATCHER)["items"][0]["hold"] == hold
    cancelled = setup.executor.cancel(TEACHER, setup.document["id"], setup.job_id)
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["outbox_hold"] == hold
    assert restarted.status(DISPATCHER)["items"][0]["state"] == "CANCELLED"
    assert hold_count(setup) == 1


@pytest.mark.parametrize(
    "corruption",
    [
        "bad_json",
        "bad_sha",
        "paid_stage",
        "foreign_binding",
        "missing_execution",
        "invalid_execution",
        "missing_checkpoint",
    ],
)
def test_poison_pending_control_records_are_quarantined_without_rewriting_evidence(
    outbox_setup, corruption
):
    setup = outbox_setup
    with setup.control.repository.connection() as connection:
        if corruption == "bad_json":
            connection.execute(
                "UPDATE offline_validation_jobs SET document=? WHERE id=?",
                ("broken{", setup.job_id),
            )
        elif corruption == "bad_sha":
            connection.execute(
                "UPDATE offline_validation_jobs SET sha256=? WHERE id=?", ("0" * 64, setup.job_id)
            )
        elif corruption == "missing_execution":
            connection.execute("DELETE FROM offline_job_execution WHERE job_id=?", (setup.job_id,))
        elif corruption == "invalid_execution":
            connection.execute(
                "UPDATE offline_job_execution SET document=? WHERE job_id=?",
                ("broken{", setup.job_id),
            )
        elif corruption == "missing_checkpoint":
            connection.execute(
                "UPDATE workspace_checkpoints SET manifest=? WHERE id=?",
                ("{}", setup.job["intent"]["checkpoint_id"]),
            )
    if corruption in ("paid_stage", "foreign_binding"):
        intent = json.loads(stored_intent(setup)[0])
        if corruption == "paid_stage":
            intent["stage"] = "grade"
        else:
            intent["binding"]["tenant_id"] = OTHER_DISPATCHER.tenant_id
        rewrite_intent(setup, intent)
    poisoned = stored_intent(setup)
    assert setup.outbox.reconcile(DISPATCHER)["items"][0]["state"] == "QUARANTINED"
    status = setup.outbox.status(DISPATCHER)["items"][0]
    assert status["state"] == "QUARANTINED"
    assert status["hold"]["reason_code"] == "JOB_INTEGRITY"
    assert "broken" not in json.dumps(status)
    assert setup.outbox.status(OTHER_DISPATCHER)["items"] == []
    assert setup.outbox.reconcile(DISPATCHER)["items"] == []
    assert stored_intent(setup) == poisoned
    assert setup.control.pending(DISPATCHER) == []
    assert setup.control.repository.get(setup.document["id"]) == setup.document
    assert hold_count(setup) == 1
    assert not setup.executor.workspace.root.exists()


@pytest.mark.parametrize("principal", [TEACHER, WORKER, ADMIN])
def test_outbox_reconciliation_and_status_require_trusted_dispatcher(outbox_setup, principal):
    setup = outbox_setup
    for action in (setup.outbox.status, setup.outbox.reconcile):
        with pytest.raises(ApplicationError) as error:
            action(principal)
        assert error.value.status == 403
    assert hold_count(setup) == 0


def test_outbox_inspection_and_mutation_do_not_cross_tenants(outbox_setup):
    setup = outbox_setup
    change_inputs(setup)
    assert setup.outbox.status(OTHER_DISPATCHER)["items"] == []
    assert setup.outbox.reconcile(OTHER_DISPATCHER)["items"] == []
    with pytest.raises(ApplicationError) as error:
        setup.outbox._reconcile_one(OTHER_DISPATCHER, setup.job_id)
    assert error.value.status == 404
    assert hold_count(setup) == 0


@pytest.mark.parametrize("limit", [0, 51, True, "20"])
def test_outbox_page_limits_and_cursor_are_strict(outbox_setup, limit):
    setup = outbox_setup
    for method in (setup.outbox.status, setup.outbox.reconcile):
        with pytest.raises(ApplicationError) as error:
            method(DISPATCHER, limit=limit)
        assert error.value.code == "INVALID_LIMIT"
        with pytest.raises(ApplicationError) as error:
            method(DISPATCHER, cursor="../bad-cursor")
        assert error.value.code == "INVALID_CURSOR"


def test_cursor_progresses_past_unchanged_current_jobs_to_later_poison(outbox_setup):
    setup = outbox_setup
    jobs = [setup.job]
    for _ in range(4):
        jobs.append(
            setup.control.request_validation(
                TEACHER,
                setup.document["id"],
                setup.document["version"],
                setup.request.model_copy(update={"request_id": uuid4()}),
            )
        )
    identifiers = sorted(job["intent"]["id"] for job in jobs)
    with setup.control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_validation_jobs SET sha256=? WHERE id=?", ("0" * 64, identifiers[-1])
        )
    cursor = None
    seen = []
    states = []
    while True:
        page = setup.outbox.reconcile(DISPATCHER, limit=2, cursor=cursor)
        seen.extend(item["job_id"] for item in page["items"])
        states.extend(item["state"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        cursor = UUID(cursor)
    assert seen == identifiers
    assert states == ["CURRENT"] * 4 + ["QUARANTINED"]
    assert hold_count(setup) == 1
    status_page = setup.outbox.status(DISPATCHER, limit=2)
    assert [item["job_id"] for item in status_page["items"]] == identifiers[:2]
    assert status_page["next_cursor"] == identifiers[1]


@pytest.mark.parametrize("winning_change", ["assign", "cancel", "inputs"])
def test_reconciliation_rechecks_control_after_candidate_scan(
    outbox_setup, monkeypatch, winning_change
):
    setup = outbox_setup
    original = setup.outbox._reconcile_one

    def changed_after_scan(principal, job_id):
        if winning_change == "assign":
            dispatch(setup.control, setup.job)
        elif winning_change == "cancel":
            setup.executor.cancel(TEACHER, setup.document["id"], setup.job_id)
        else:
            change_inputs(setup)
        return original(principal, job_id)

    monkeypatch.setattr(setup.outbox, "_reconcile_one", changed_after_scan)
    report = setup.outbox.reconcile(DISPATCHER)["items"][0]
    assert report["state"] == ("STALE" if winning_change == "inputs" else "SKIPPED")
    assert hold_count(setup) == (1 if winning_change == "inputs" else 0)


def test_transient_control_errors_are_not_terminal_quarantine(outbox_setup, monkeypatch):
    setup = outbox_setup

    def unavailable(_job):
        raise ApplicationError("CONTROL_UNAVAILABLE", "Temporary storage failure.", 503)

    monkeypatch.setattr(setup.control, "_current", unavailable)
    with pytest.raises(ApplicationError) as error:
        setup.outbox.reconcile(DISPATCHER)
    assert error.value.status == 503
    assert hold_count(setup) == 0
    assert setup.control.jobs.get(setup.job_id) == setup.job


def test_hold_insert_failure_rolls_back_without_changing_job_or_approval(outbox_setup):
    setup = outbox_setup
    updated = change_inputs(setup)
    original = stored_intent(setup)
    with setup.control.repository.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_hold BEFORE INSERT ON offline_outbox_holds "
            "BEGIN SELECT RAISE(ABORT, 'synthetic hold failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        setup.outbox.reconcile(DISPATCHER)
    assert hold_count(setup) == 0
    assert stored_intent(setup) == original
    assert setup.control.repository.get(setup.document["id"]) == updated
    with setup.control.repository.connection() as connection:
        connection.execute("DROP TRIGGER fail_hold")
    assert setup.outbox.reconcile(DISPATCHER)["items"][0]["state"] == "STALE"
    assert hold_count(setup) == 1


def test_concurrent_reconciliation_records_only_one_immutable_hold(outbox_setup, monkeypatch):
    setup = outbox_setup
    change_inputs(setup)
    barrier = Barrier(2)
    original = setup.outbox._page

    def simultaneous_scan(*args, **kwargs):
        page = original(*args, **kwargs)
        barrier.wait(timeout=10)
        return page

    monkeypatch.setattr(setup.outbox, "_page", simultaneous_scan)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: setup.outbox.reconcile(DISPATCHER), range(2)))
    assert [report["items"][0]["state"] for report in outcomes] == ["STALE", "STALE"]
    assert hold_count(setup) == 1
    assert setup.control.jobs.get(setup.job_id)["outbox_hold"]["actor_id"] == DISPATCHER.object_id


def test_rehashed_foreign_hold_cannot_replace_local_audit_scope(outbox_setup):
    setup = outbox_setup
    change_inputs(setup)
    setup.outbox.reconcile(DISPATCHER)
    hold = setup.control.jobs.get(setup.job_id)["outbox_hold"]
    hold["tenant_id"] = OTHER_DISPATCHER.tenant_id
    encoded = json.dumps(hold, sort_keys=True, separators=(",", ":"))
    with setup.control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_outbox_holds SET document=?, sha256=? WHERE job_id=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest(), setup.job_id),
        )
    for action in (
        lambda: setup.outbox.status(DISPATCHER),
        lambda: setup.control.jobs.get(setup.job_id),
    ):
        with pytest.raises(ApplicationError) as error:
            action()
        assert error.value.code == "JOB_INTEGRITY"
    assert setup.outbox.status(OTHER_DISPATCHER)["items"] == []
    assert setup.control.pending(DISPATCHER) == []
