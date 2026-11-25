import hashlib
import json
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import ADMIN, OTHER_TEACHER, OTHER_TENANT, TEACHER, WORKER
from test_execution import Clock
from test_jobs import DISPATCHER, FOREIGN_WORKER, OTHER_WORKER
from test_workspace import approved_review

from handwriting_grader_cloud.coordinator import OfflineJobCoordinator
from handwriting_grader_cloud.delivery import OfflineDispatcher, QueueMessage, SimulatedQueue
from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.execution import CLAIM_DURATION, OfflineValidationExecutor
from handwriting_grader_cloud.jobs import OfflineJobControl
from handwriting_grader_cloud.models import OfflineValidationRequest
from handwriting_grader_cloud.preflight import EngineInputValidator
from handwriting_grader_cloud.workspace import WorkspaceBridge

pytestmark = pytest.mark.engine


@pytest.fixture(autouse=True)
def no_paid_actions(monkeypatch):
    from handwriting_grader import attendance, grading, regions, rubric

    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline coordination must never approve or grade.")

    for module, name in (
        (grading, "grade_exam"),
        (attendance, "approve_attendance"),
        (regions, "approve_regions"),
        (rubric, "approve_rubric"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.fixture
def coordinator_setup(client, service, tmp_path, request):
    document = approved_review(client, getattr(request, "param", False)).json()
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
    queue = SimulatedQueue()
    clock = Clock()
    dispatcher = OfflineDispatcher(control, queue, clock=clock)
    executor = OfflineValidationExecutor(control, tmp_path / "execution", clock=clock)
    return SimpleNamespace(
        document=document,
        job=job,
        job_id=job["intent"]["id"],
        message_id=job["intent"]["message_id"],
        control=control,
        queue=queue,
        clock=clock,
        dispatcher=dispatcher,
        executor=executor,
        coordinator=OfflineJobCoordinator(control, dispatcher, executor),
    )


def send(setup):
    return setup.dispatcher.dispatch(DISPATCHER, setup.job_id, setup.message_id, WORKER, uuid4())


def consume(setup, principal=WORKER, payload=None):
    return setup.coordinator.consume(
        principal, setup.queue.messages[0] if payload is None else payload, uuid4()
    )


def status(setup, principal=TEACHER):
    return setup.coordinator.owned_status(principal, setup.document["id"], setup.job_id)


def change_inputs(setup):
    document = setup.document
    return setup.control.bridge.service.settings(
        TEACHER, document["id"], document["version"], document["settings"]
    )


@pytest.mark.parametrize("coordinator_setup", [False, True], indirect=True)
def test_real_confirmed_queue_consumption_and_owner_lifecycle_reuse_result(
    coordinator_setup, monkeypatch
):
    setup = coordinator_setup
    assert status(setup)["state"] == "PENDING_DISPATCH"
    assert status(setup)["eligible_for_validation"] is False
    send(setup)
    ready = status(setup)
    assert ready["state"] == "READY_FOR_VALIDATION"
    assert ready["eligible_for_validation"] is True
    assert ready["result_available"] is False
    original = EngineInputValidator.validate
    states = []

    def validated(self, document, contents):
        states.append(status(setup)["state"])
        return original(self, document, contents)

    monkeypatch.setattr(EngineInputValidator, "validate", validated)
    result = consume(setup)
    assert result["summary"] == setup.document["preflight"]["summary"]
    completed = status(setup)
    assert completed["state"] == "VALIDATED"
    assert completed["current_job_scope"] is True
    assert completed["eligible_for_validation"] is False
    assert completed["result_available"] is True
    assert consume(setup) == result
    assert setup.coordinator.owned_result(TEACHER, setup.document["id"], setup.job_id) == result
    assert states == ["VALIDATION_RUNNING"]
    assert setup.control.repository.get(setup.document["id"]) == setup.document
    assert list(setup.executor.workspace.root.iterdir()) == []


@pytest.mark.parametrize(
    "extra,value",
    [
        ("stage", "grade"),
        ("role", "Teacher"),
        ("path", "/private/scans.pdf"),
        ("receipt_id", "forged"),
        ("attempt_id", "caller-choice"),
    ],
)
def test_queue_envelope_cannot_supply_stage_role_paths_or_execution_authority(
    coordinator_setup, extra, value
):
    setup = coordinator_setup
    send(setup)
    payload = {**asdict(setup.queue.messages[0]), extra: value}
    with pytest.raises(ApplicationError) as error:
        consume(setup, payload=payload)
    assert error.value.code == "INVALID_MESSAGE"
    assert not setup.executor.workspace.root.exists()
    assert status(setup)["state"] == "READY_FOR_VALIDATION"


@pytest.mark.parametrize(
    "principal,status_code",
    [
        (TEACHER, 403),
        (ADMIN, 403),
        (OTHER_WORKER, 404),
        (FOREIGN_WORKER, 404),
    ],
)
def test_queue_consumption_requires_authenticated_assigned_worker(
    coordinator_setup, principal, status_code
):
    setup = coordinator_setup
    send(setup)
    with pytest.raises(ApplicationError) as error:
        consume(setup, principal=principal)
    assert error.value.status == status_code
    assert status(setup)["result_available"] is False


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("worker_id", "another-worker", "NOT_FOUND"),
        ("message_id", str(uuid4()), "NOT_FOUND"),
        ("job_id", str(uuid4()), "NOT_FOUND"),
        ("job_id", "../outside", "INVALID_MESSAGE"),
        ("worker_id", True, "INVALID_MESSAGE"),
    ],
)
def test_opaque_message_ids_and_recipient_are_not_authority(coordinator_setup, field, value, code):
    setup = coordinator_setup
    send(setup)
    payload = {**asdict(setup.queue.messages[0]), field: value}
    with pytest.raises(ApplicationError) as error:
        consume(setup, payload=payload)
    assert error.value.code == code
    assert not setup.executor.workspace.root.exists()


def test_legacy_assignment_does_not_authorize_queue_consumption(coordinator_setup):
    setup = coordinator_setup
    setup.control.acknowledge_dispatch(DISPATCHER, setup.job_id, setup.message_id, WORKER)
    assert status(setup)["state"] == "ASSIGNED_WITHOUT_DELIVERY"
    payload = QueueMessage(setup.job_id, setup.message_id, WORKER.object_id)
    with pytest.raises(ApplicationError) as error:
        consume(setup, payload=payload)
    assert error.value.code == "DELIVERY_REQUIRED"
    assert not setup.executor.workspace.root.exists()


def test_accepted_unconfirmed_message_is_not_consumer_authority(coordinator_setup):
    setup = coordinator_setup
    setup.queue.failures.append("ack_lost")
    record = send(setup)
    assert status(setup)["state"] == "DELIVERY_RETRY_WAIT"
    with pytest.raises(ApplicationError) as error:
        consume(setup)
    assert error.value.status == 404
    setup.clock.now = setup.dispatcher._time(record["next_attempt_at"])
    assert status(setup)["state"] == "DELIVERY_RETRY_READY"
    send(setup)
    assert setup.queue.messages[0] == setup.queue.messages[1]
    assert consume(setup)["status"] == "passed"


@pytest.mark.parametrize(
    "principal,status_code",
    [
        (OTHER_TEACHER, 404),
        (OTHER_TENANT, 404),
        (WORKER, 403),
        (ADMIN, 403),
    ],
)
def test_lifecycle_and_historical_result_inspection_are_owner_teacher_scoped(
    coordinator_setup, principal, status_code
):
    setup = coordinator_setup
    for operation in (
        lambda: status(setup, principal),
        lambda: setup.coordinator.owned_result(principal, setup.document["id"], setup.job_id),
    ):
        with pytest.raises(ApplicationError) as error:
            operation()
        assert error.value.status == status_code


def test_owner_lifecycle_tracks_live_and_expired_claims_without_starting_work(coordinator_setup):
    setup = coordinator_setup
    send(setup)
    claim = setup.executor.claim(WORKER, setup.job_id, setup.message_id, uuid4())
    assert status(setup)["state"] == "VALIDATION_CLAIMED"
    assert status(setup)["eligible_for_validation"] is False
    context = setup.control.worker_context(WORKER, setup.job_id, setup.message_id)
    setup.executor._begin(WORKER, context, claim)
    assert status(setup)["state"] == "VALIDATION_RUNNING"
    setup.clock.now += CLAIM_DURATION
    expired = status(setup)
    assert expired["state"] == "VALIDATION_CLAIM_EXPIRED"
    assert expired["eligible_for_validation"] is True
    assert not setup.executor.workspace.root.exists()
    assert consume(setup)["status"] == "passed"
    assert status(setup)["state"] == "VALIDATED"


@pytest.mark.parametrize("change", ["cancel", "stale"])
def test_cancelled_or_stale_job_is_inspectable_but_cannot_be_consumed(coordinator_setup, change):
    setup = coordinator_setup
    send(setup)
    if change == "cancel":
        setup.executor.cancel(TEACHER, setup.document["id"], setup.job_id)
    else:
        change_inputs(setup)
    view = status(setup)
    assert view["state"] == ("CANCELLED" if change == "cancel" else "STALE_INPUTS")
    assert view["current_job_scope"] is False
    assert view["eligible_for_validation"] is False
    with pytest.raises(ApplicationError) as error:
        consume(setup)
    assert error.value.code == ("JOB_CANCELLED" if change == "cancel" else "STALE_JOB")
    assert not setup.executor.workspace.root.exists()


def test_old_validation_result_is_explicitly_historical_after_input_changes(coordinator_setup):
    setup = coordinator_setup
    send(setup)
    result = consume(setup)
    change_inputs(setup)
    view = status(setup)
    assert view["state"] == "VALIDATED_HISTORICAL"
    assert view["result_available"] is True
    assert view["current_job_scope"] is False
    assert view["eligible_for_validation"] is False
    assert setup.coordinator.owned_result(TEACHER, setup.document["id"], setup.job_id) == result


def test_owner_lifecycle_exposes_exhausted_delivery_hold_without_auto_release(coordinator_setup):
    setup = coordinator_setup
    setup.queue.failures.extend(["not_accepted"] * 3)
    for number in range(3):
        delivery = send(setup)
        if number < 2:
            setup.clock.now = setup.dispatcher._time(delivery["next_attempt_at"])
    view = status(setup)
    assert view["state"] == "DELIVERY_REVIEW"
    assert view["outbox_hold"]["reason_code"] == "DELIVERY_ATTEMPTS_EXHAUSTED"
    assert view["eligible_for_validation"] is False
    assert setup.queue.send_count == 3
    assert not setup.executor.workspace.root.exists()


def test_owner_lifecycle_rechecks_version_after_snapshot_inspection(coordinator_setup, monkeypatch):
    setup = coordinator_setup
    original = setup.control._current

    def changed_after_read(job):
        checkpoint = original(job)
        change_inputs(setup)
        return checkpoint

    monkeypatch.setattr(setup.control, "_current", changed_after_read)
    with pytest.raises(ApplicationError) as error:
        status(setup)
    assert error.value.code == "STALE_REVIEW"
    assert setup.queue.send_count == 0


def test_corrupt_committed_result_cannot_be_reported_as_success(coordinator_setup):
    setup = coordinator_setup
    send(setup)
    consume(setup)
    with setup.control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_validation_results SET document=? WHERE job_id=?",
            ("corrupt", setup.job_id),
        )
    with pytest.raises(ApplicationError) as error:
        status(setup)
    assert error.value.code == "JOB_INTEGRITY"


def test_consumer_cannot_bypass_another_live_execution_claim(coordinator_setup):
    setup = coordinator_setup
    send(setup)
    setup.executor.claim(WORKER, setup.job_id, setup.message_id, uuid4())
    with pytest.raises(ApplicationError) as error:
        consume(setup)
    assert error.value.code == "JOB_CLAIMED"
    assert not setup.executor.workspace.root.exists()
    assert status(setup)["result_available"] is False


def test_owner_can_inspect_expired_unknown_send_without_triggering_a_retry(
    coordinator_setup, monkeypatch
):
    setup = coordinator_setup

    def crash(*_args):
        raise RuntimeError("Synthetic unknown enqueue outcome.")

    monkeypatch.setattr(setup.dispatcher, "_finish", crash)
    with pytest.raises(RuntimeError):
        send(setup)
    assert status(setup)["state"] == "DELIVERY_SENDING"
    setup.clock.now += CLAIM_DURATION
    view = status(setup)
    assert view["state"] == "DELIVERY_SEND_EXPIRED"
    assert view["eligible_for_validation"] is False
    assert setup.queue.send_count == 1
    assert not setup.executor.workspace.root.exists()


def test_consumer_validates_protected_delivery_record_not_just_envelope(coordinator_setup):
    setup = coordinator_setup
    delivery = send(setup)
    delivery["stage"] = "grade"
    encoded = json.dumps(delivery, sort_keys=True, separators=(",", ":"))
    with setup.control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_delivery_control SET document=?, sha256=? WHERE job_id=?",
            (encoded, hashlib.sha256(encoded.encode()).hexdigest(), setup.job_id),
        )
    with pytest.raises(ApplicationError) as error:
        consume(setup)
    assert error.value.code == "JOB_INTEGRITY"
    assert not setup.executor.workspace.root.exists()
