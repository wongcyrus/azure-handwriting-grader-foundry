import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import ADMIN, TEACHER, WORKER
from test_execution import Clock
from test_jobs import DISPATCHER, FOREIGN_WORKER, OTHER_DISPATCHER, OTHER_WORKER
from test_workspace import approved_review

from handwriting_grader_cloud.delivery import OfflineDispatcher, SimulatedQueue
from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.execution import CLAIM_DURATION, OfflineValidationExecutor
from handwriting_grader_cloud.jobs import OfflineJobControl
from handwriting_grader_cloud.models import OfflineValidationRequest
from handwriting_grader_cloud.outbox import OutboxReconciler
from handwriting_grader_cloud.preflight import EngineInputValidator
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService
from handwriting_grader_cloud.workspace import WorkspaceBridge

pytestmark = pytest.mark.engine


@pytest.fixture(autouse=True)
def no_paid_actions(monkeypatch):
    from handwriting_grader import attendance, grading, regions, rubric

    def forbidden(*_args, **_kwargs):
        pytest.fail("Simulated delivery must never approve or grade.")

    for module, name in (
        (grading, "grade_exam"),
        (attendance, "approve_attendance"),
        (regions, "approve_regions"),
        (rubric, "approve_rubric"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.fixture
def delivery_setup(client, service, tmp_path, request):
    document = approved_review(client).json()
    bridge = WorkspaceBridge(service, tmp_path / "review")
    workspace = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    control = OfflineJobControl(bridge)
    job = control.request_validation(
        TEACHER,
        document["id"],
        document["version"],
        OfflineValidationRequest(
            checkpoint_id=workspace.checkpoint_id, request_id=uuid4(), confirmed=True
        ),
    )
    clock = Clock()
    queue = SimulatedQueue(getattr(request, "param", ()))
    return SimpleNamespace(
        document=document,
        control=control,
        job=job,
        job_id=job["intent"]["id"],
        message_id=job["intent"]["message_id"],
        clock=clock,
        queue=queue,
        dispatcher=OfflineDispatcher(control, queue, clock=clock),
        executor=OfflineValidationExecutor(control, tmp_path / "execution", clock=clock),
    )


def send(setup, nonce=None, principal=DISPATCHER, worker=WORKER):
    return setup.dispatcher.dispatch(
        principal, setup.job_id, setup.message_id, worker, nonce or uuid4()
    )


def advance_to_retry(setup, delivery):
    setup.clock.now = setup.dispatcher._time(delivery["next_attempt_at"])


def test_confirmed_simulated_delivery_is_durable_and_replay_does_not_resend(
    delivery_setup, tmp_path
):
    setup = delivery_setup
    assert setup.dispatcher.status(DISPATCHER, setup.job_id) is None
    delivery = send(setup)
    assert delivery["state"] == "DELIVERED"
    assert len(delivery["attempts"]) == 1
    assert setup.queue.send_count == 1
    message = setup.queue.messages[0]
    assert message.job_id == setup.job_id
    assert message.message_id == setup.message_id
    assert message.worker_id == WORKER.object_id
    assert send(setup) == delivery
    restarted = OfflineDispatcher(
        OfflineJobControl(
            WorkspaceBridge(
                ExamService(SQLiteRepository(setup.control.repository.path)), tmp_path / "restart"
            )
        ),
        setup.queue,
        clock=setup.clock,
    )
    assert (
        restarted.dispatch(DISPATCHER, setup.job_id, setup.message_id, WORKER, uuid4()) == delivery
    )
    assert setup.queue.send_count == 1
    assert (
        setup.control.worker_context(WORKER, setup.job_id, setup.message_id)["stage"]
        == "validate_engine_inputs"
    )
    assert setup.control.repository.get(setup.document["id"]) == setup.document
    assert not setup.executor.workspace.root.exists()


@pytest.mark.parametrize("delivery_setup", [("not_accepted",), ("ack_lost",)], indirect=True)
def test_retry_wait_is_server_owned_and_stable_nonce_does_not_increment(delivery_setup):
    setup = delivery_setup
    nonce = uuid4()
    first = send(setup, nonce)
    assert first["state"] == "RETRY_WAIT"
    assert (setup.dispatcher._time(first["next_attempt_at"]) - setup.clock.now).total_seconds() == 5
    assert send(setup, nonce) == first
    assert send(setup)["state"] == "RETRY_WAIT"
    assert setup.queue.send_count == 1
    advance_to_retry(setup, first)
    delivered = send(setup)
    assert delivered["state"] == "DELIVERED"
    assert len(delivered["attempts"]) == 2
    assert setup.queue.send_count == 2


@pytest.mark.parametrize(
    "delivery_setup", [("not_accepted",) * 3, ("ack_lost",) * 3], indirect=True
)
def test_three_unconfirmed_attempts_stop_in_immutable_operator_review(delivery_setup):
    setup = delivery_setup
    first = send(setup)
    advance_to_retry(setup, first)
    second = send(setup)
    assert (
        setup.dispatcher._time(second["next_attempt_at"]) - setup.clock.now
    ).total_seconds() == 30
    advance_to_retry(setup, second)
    exhausted = send(setup)
    assert exhausted["state"] == "EXHAUSTED"
    assert len(exhausted["attempts"]) == 3
    assert setup.queue.send_count == 3
    assert setup.control.jobs.get(setup.job_id)["worker_id"] is None
    assert setup.control.pending(DISPATCHER) == []
    hold = OutboxReconciler(setup.control).status(DISPATCHER)["items"][0]["hold"]
    assert hold["state"] == "DELIVERY_REVIEW"
    assert hold["reason_code"] == "DELIVERY_ATTEMPTS_EXHAUSTED"
    setup.clock.now += CLAIM_DURATION * 2
    assert send(setup) == exhausted
    assert setup.queue.send_count == 3
    assert setup.control.jobs.get(setup.job_id)["outbox_hold"] == hold


@pytest.mark.parametrize("delivery_setup", [("ack_lost",)], indirect=True)
def test_duplicate_accepted_messages_share_one_job_and_reuse_validation_result(
    delivery_setup, monkeypatch
):
    setup = delivery_setup
    first = send(setup)
    with pytest.raises(ApplicationError) as error:
        setup.control.worker_context(WORKER, setup.job_id, setup.message_id)
    assert error.value.status == 404
    advance_to_retry(setup, first)
    send(setup)
    assert setup.queue.messages[0] == setup.queue.messages[1]
    original = EngineInputValidator.validate
    calls = []

    def validated(self, document, contents):
        calls.append(document["id"])
        return original(self, document, contents)

    monkeypatch.setattr(EngineInputValidator, "validate", validated)
    results = [
        setup.executor.run(WORKER, message.job_id, message.message_id, uuid4())
        for message in setup.queue.messages
    ]
    assert results[0] == results[1]
    assert results[0]["status"] == "passed"
    assert calls == [setup.document["id"]]


@pytest.mark.parametrize("phase", ["before_send", "after_send"])
def test_crash_watermark_survives_expiry_and_replacement(delivery_setup, monkeypatch, phase):
    setup = delivery_setup
    nonce = uuid4()
    owner, attribute = (
        (setup.queue, "send") if phase == "before_send" else (setup.dispatcher, "_finish")
    )
    original = getattr(owner, attribute)

    def crash(*_args, **_kwargs):
        raise RuntimeError("Synthetic crash at delivery boundary.")

    monkeypatch.setattr(owner, attribute, crash)
    with pytest.raises(RuntimeError):
        send(setup, nonce)
    in_flight = setup.dispatcher.status(DISPATCHER, setup.job_id)
    assert in_flight["state"] == "SENDING"
    assert setup.control.jobs.get(setup.job_id)["worker_id"] is None
    assert send(setup, nonce) == in_flight
    with pytest.raises(ApplicationError) as error:
        send(setup)
    assert error.value.code == "DELIVERY_IN_FLIGHT"
    monkeypatch.setattr(owner, attribute, original)
    setup.clock.now += CLAIM_DURATION
    waiting = send(setup)
    assert waiting["state"] == "RETRY_WAIT"
    advance_to_retry(setup, waiting)
    delivered = send(setup)
    assert delivered["state"] == "DELIVERED"
    assert delivered["attempts"][0]["state"] == "EXPIRED"
    assert len(delivered["attempts"]) == 2


def test_replaced_send_cannot_confirm_a_late_receipt(delivery_setup, monkeypatch):
    setup = delivery_setup
    old_nonce = uuid4()
    original = setup.dispatcher._finish

    def crash(*_args):
        raise RuntimeError("Synthetic lost acknowledgement.")

    monkeypatch.setattr(setup.dispatcher, "_finish", crash)
    with pytest.raises(RuntimeError):
        send(setup, old_nonce)
    monkeypatch.setattr(setup.dispatcher, "_finish", original)
    setup.clock.now += CLAIM_DURATION
    advance_to_retry(setup, send(setup))
    delivered = send(setup)
    with pytest.raises(ApplicationError) as error:
        original(DISPATCHER, setup.job_id, setup.message_id, WORKER, str(old_nonce), str(uuid4()))
    assert error.value.code == "DELIVERY_CLAIM_LOST"
    assert setup.dispatcher.status(DISPATCHER, setup.job_id) == delivered


@pytest.mark.parametrize(
    "principal,worker,status",
    [
        (TEACHER, WORKER, 403),
        (ADMIN, WORKER, 403),
        (WORKER, WORKER, 403),
        (OTHER_DISPATCHER, WORKER, 404),
        (DISPATCHER, FOREIGN_WORKER, 404),
        (DISPATCHER, TEACHER, 403),
    ],
)
def test_delivery_scope_cannot_cross_roles_or_tenants(delivery_setup, principal, worker, status):
    setup = delivery_setup
    with pytest.raises(ApplicationError) as error:
        send(setup, principal=principal, worker=worker)
    assert error.value.status == status
    assert setup.queue.send_count == 0
    assert setup.dispatcher.status(DISPATCHER, setup.job_id) is None


@pytest.mark.parametrize("delivery_setup", [("not_accepted",)], indirect=True)
def test_retry_cannot_change_recipient_or_select_another_message(delivery_setup):
    setup = delivery_setup
    send(setup)
    with pytest.raises(ApplicationError) as error:
        send(setup, worker=OTHER_WORKER)
    assert error.value.code == "DISPATCH_CONFLICT"
    for message, nonce, code in (
        (str(uuid4()), uuid4(), "NOT_FOUND"),
        (setup.message_id, "../unsafe", "INVALID_ATTEMPT"),
    ):
        with pytest.raises(ApplicationError) as error:
            setup.dispatcher.dispatch(DISPATCHER, setup.job_id, message, WORKER, nonce)
        assert error.value.code == code
    assert setup.queue.send_count == 1


@pytest.mark.parametrize("winning_change", ["stale", "cancel"])
def test_snapshot_change_or_cancellation_during_send_prevents_assignment(
    delivery_setup, monkeypatch, winning_change
):
    setup = delivery_setup
    original = setup.queue.send

    def changed_during_send(message):
        receipt = original(message)
        if winning_change == "stale":
            setup.control.bridge.service.settings(
                TEACHER, setup.document["id"], setup.document["version"], setup.document["settings"]
            )
        else:
            setup.executor.cancel(TEACHER, setup.document["id"], setup.job_id)
        return receipt

    monkeypatch.setattr(setup.queue, "send", changed_during_send)
    with pytest.raises(ApplicationError) as error:
        send(setup)
    assert error.value.code == ("STALE_REVIEW" if winning_change == "stale" else "JOB_CANCELLED")
    assert setup.control.jobs.get(setup.job_id)["worker_id"] is None
    assert setup.queue.send_count == 1


def test_legacy_assignment_is_not_delivery_and_managed_assignment_cannot_bypass_send(
    delivery_setup, monkeypatch
):
    setup = delivery_setup
    original = setup.queue.send

    def guarded_send(message):
        with pytest.raises(ApplicationError) as error:
            setup.control.acknowledge_dispatch(
                DISPATCHER, setup.job_id, setup.message_id, OTHER_WORKER
            )
        assert error.value.code == "DELIVERY_MANAGED"
        return original(message)

    monkeypatch.setattr(setup.queue, "send", guarded_send)
    assert send(setup)["state"] == "DELIVERED"


def test_already_assigned_legacy_job_is_not_automatically_sent(delivery_setup):
    setup = delivery_setup
    setup.control.acknowledge_dispatch(DISPATCHER, setup.job_id, setup.message_id, WORKER)
    with pytest.raises(ApplicationError) as error:
        send(setup)
    assert error.value.code == "DISPATCH_ALREADY_ASSIGNED"
    assert setup.queue.send_count == 0


def test_confirmation_and_assignment_rollback_together(delivery_setup):
    setup = delivery_setup
    with setup.control.repository.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_delivery BEFORE UPDATE ON offline_delivery_control "
            "WHEN json_extract(NEW.document, '$.state')='DELIVERED' "
            "BEGIN SELECT RAISE(ABORT, 'synthetic confirmation failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        send(setup)
    assert setup.control.jobs.get(setup.job_id)["worker_id"] is None
    assert setup.dispatcher.status(DISPATCHER, setup.job_id)["state"] == "SENDING"
    with setup.control.repository.connection() as connection:
        connection.execute("DROP TRIGGER fail_delivery")
    setup.clock.now += CLAIM_DURATION
    advance_to_retry(setup, send(setup))
    assert send(setup)["state"] == "DELIVERED"


def test_concurrent_dispatchers_do_not_issue_two_live_sends(delivery_setup, monkeypatch):
    setup = delivery_setup
    original = setup.dispatcher._begin
    barrier = Barrier(2)

    def simultaneous_begin(*args):
        barrier.wait(timeout=10)
        return original(*args)

    monkeypatch.setattr(setup.dispatcher, "_begin", simultaneous_begin)

    def dispatch_one(_index):
        try:
            return send(setup)["state"]
        except ApplicationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(dispatch_one, range(2)))
    assert "DELIVERED" in outcomes
    assert all(value in ("DELIVERED", "DELIVERY_IN_FLIGHT") for value in outcomes)
    assert setup.queue.send_count == 1


@pytest.mark.parametrize("delivery_setup", [("not_accepted",)], indirect=True)
def test_rehashed_delivery_stage_corruption_fails_closed(delivery_setup):
    setup = delivery_setup
    document = send(setup)
    document["stage"] = "grade"
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"))
    with setup.control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_delivery_control SET document=?, sha256=? WHERE job_id=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest(), setup.job_id),
        )
    with pytest.raises(ApplicationError) as error:
        send(setup)
    assert error.value.code == "JOB_INTEGRITY"
    assert setup.queue.send_count == 1


def test_three_expired_unknown_send_attempts_cannot_issue_a_fourth(delivery_setup, monkeypatch):
    setup = delivery_setup

    def crash(*_args):
        raise RuntimeError("Synthetic unknown submission outcome.")

    monkeypatch.setattr(setup.dispatcher, "_finish", crash)
    for number in range(1, 4):
        with pytest.raises(RuntimeError):
            send(setup)
        record = setup.dispatcher.status(DISPATCHER, setup.job_id)
        assert len(record["attempts"]) == number
        setup.clock.now = setup.dispatcher._time(record["attempts"][-1]["expires_at"])
        outcome = send(setup)
        if number < 3:
            assert outcome["state"] == "RETRY_WAIT"
            advance_to_retry(setup, outcome)
        else:
            assert outcome["state"] == "EXHAUSTED"
    assert setup.queue.send_count == 3
    assert setup.control.jobs.get(setup.job_id)["state"] == "DELIVERY_REVIEW"


@pytest.mark.parametrize("delivery_setup", [("not_accepted",) * 3], indirect=True)
def test_exhaustion_hold_failure_preserves_attempt_limit_and_recovers(delivery_setup):
    setup = delivery_setup
    first = send(setup)
    advance_to_retry(setup, first)
    second = send(setup)
    advance_to_retry(setup, second)
    with setup.control.repository.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_review BEFORE INSERT ON offline_outbox_holds "
            "BEGIN SELECT RAISE(ABORT, 'synthetic review write failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        send(setup)
    assert setup.queue.send_count == 3
    assert setup.dispatcher.status(DISPATCHER, setup.job_id)["state"] == "SENDING"
    with setup.control.repository.connection() as connection:
        connection.execute("DROP TRIGGER fail_review")
    setup.clock.now += CLAIM_DURATION
    assert send(setup)["state"] == "EXHAUSTED"
    assert setup.queue.send_count == 3


def test_expiry_at_confirmation_boundary_cannot_grant_worker_read_access(
    delivery_setup, monkeypatch
):
    setup = delivery_setup
    nonce = uuid4()
    original = setup.dispatcher._finish

    def crash(*_args):
        raise RuntimeError("Synthetic interruption before confirmation.")

    monkeypatch.setattr(setup.dispatcher, "_finish", crash)
    with pytest.raises(RuntimeError):
        send(setup, nonce)
    document = setup.dispatcher.status(DISPATCHER, setup.job_id)
    deadline = setup.dispatcher._time(document["attempts"][-1]["expires_at"])
    times = iter([deadline - timedelta(microseconds=1), deadline])
    setup.dispatcher.clock = lambda: next(times)
    with pytest.raises(ApplicationError) as error:
        original(DISPATCHER, setup.job_id, setup.message_id, WORKER, str(nonce), str(uuid4()))
    assert error.value.code == "DELIVERY_CLAIM_LOST"
    assert setup.control.jobs.get(setup.job_id)["worker_id"] is None


def test_delivery_history_is_visible_only_to_its_tenant_dispatcher(delivery_setup):
    setup = delivery_setup
    send(setup)
    for principal, status in ((OTHER_DISPATCHER, 404), (TEACHER, 403), (ADMIN, 403)):
        with pytest.raises(ApplicationError) as error:
            setup.dispatcher.status(principal, setup.job_id)
        assert error.value.status == status
