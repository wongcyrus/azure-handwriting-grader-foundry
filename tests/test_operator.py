import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import conftest
import pytest
from test_execution import Clock
from test_workspace import approved_review

from handwriting_grader_cloud import operator
from handwriting_grader_cloud.auth import DEVELOPMENT_TENANT_ID, Principal
from handwriting_grader_cloud.coordinator import OfflineJobCoordinator
from handwriting_grader_cloud.delivery import OfflineDispatcher, SimulatedQueue
from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.execution import OfflineValidationExecutor
from handwriting_grader_cloud.models import OfflineValidationRequest
from handwriting_grader_cloud.outbox import OutboxReconciler
from handwriting_grader_cloud.preflight import EngineInputValidator

pytestmark = pytest.mark.engine


@pytest.fixture(autouse=True)
def forbid_paid_and_approval_actions(monkeypatch):
    from handwriting_grader import attendance, grading, regions, rubric

    def forbidden(*_args, **_kwargs):
        pytest.fail("The local operator must not approve or grade.")

    for module, name in (
        (attendance, "approve_attendance"),
        (grading, "grade_exam"),
        (regions, "approve_regions"),
        (rubric, "approve_rubric"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.fixture
def operator_setup(client, service, monkeypatch, tmp_path, request):
    teacher = (
        conftest.TEACHER
        if getattr(request, "param", None) == "foreign"
        else Principal(
            DEVELOPMENT_TENANT_ID,
            "00000000-0000-0000-0000-000000000002",
            frozenset({"Teacher"}),
        )
    )
    monkeypatch.setattr(conftest, "TEACHER", teacher)
    document = approved_review(client, getattr(request, "param", None) is True).json()
    control = client.app.state.offline_jobs
    prepared = control.bridge.prepare_engine_inputs(teacher, document["id"], document["version"])
    intent = OfflineValidationRequest(
        checkpoint_id=prepared.checkpoint_id, request_id=uuid4(), confirmed=True
    )
    job = control.request_validation(teacher, document["id"], document["version"], intent)
    clock = Clock()
    queue = SimulatedQueue()
    coordinator = OfflineJobCoordinator(
        control,
        OfflineDispatcher(control, queue, clock=clock),
        OfflineValidationExecutor(control, tmp_path / "validation", clock=clock),
    )
    return SimpleNamespace(
        teacher=teacher,
        document=document,
        control=control,
        intent=intent,
        job=job,
        job_id=UUID(job["intent"]["id"]),
        clock=clock,
        queue=queue,
        coordinator=coordinator,
        args=[
            "--development",
            "--database",
            str(service.repository.path),
            "--job-id",
            job["intent"]["id"],
        ],
    )


@pytest.mark.parametrize("operator_setup", [False, True], indirect=True)
def test_cli_validates_one_real_job_and_fresh_invocation_reuses_result(
    operator_setup, capsys, monkeypatch
):
    setup = operator_setup
    assert operator.main(setup.args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["state"] == "VALIDATED"
    assert first["delivery_sends"] == first["delivery_attempts"] == 1
    assert first["summary"] == {
        key: setup.document["preflight"]["summary"][key]
        for key in ("students", "absent", "pdf_pages", "total_marks")
    }
    assert first["summary"]["students"] == (1 if "attendance" in setup.document["artifacts"] else 2)
    assert setup.control.repository.get(setup.document["id"]) == setup.document
    job = setup.control.jobs.get(str(setup.job_id))
    assert job["worker_id"] == operator.SYNTHETIC_WORKER.object_id
    assert job["execution"]["fence"] == 1

    def forbidden(*_args, **_kwargs):
        pytest.fail("A known result must not revalidate.")

    monkeypatch.setattr(EngineInputValidator, "validate", forbidden)
    assert operator.main(setup.args) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["delivery_sends"] == 0
    assert replay["result_sha256"] == first["result_sha256"]
    assert replay["validated_at"] == first["validated_at"]
    assert setup.control.jobs.get(str(setup.job_id)) == job


def test_cli_requires_development_before_touching_database(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(SystemExit) as error:
        operator.main(["--database", str(missing), "--job-id", str(uuid4())])
    assert error.value.code == 2
    assert not missing.exists()


def test_cli_cannot_select_tenant_recipient_or_paid_stage(operator_setup):
    setup = operator_setup
    for option in ("--tenant-id", "--worker-id", "--stage"):
        with pytest.raises(SystemExit) as error:
            operator.main([*setup.args, option, "caller-selected"])
        assert error.value.code == 2
    assert setup.control.jobs.get(str(setup.job_id)) == setup.job


@pytest.mark.parametrize("operator_setup", ["foreign"], indirect=True)
def test_operator_fixed_development_tenant_cannot_touch_foreign_job(operator_setup, capsys):
    setup = operator_setup
    assert operator.main(setup.args) == 1
    assert json.loads(capsys.readouterr().out) == {"error": {"code": "NOT_FOUND"}}
    assert setup.control.jobs.get(str(setup.job_id)) == setup.job
    assert setup.queue.send_count == 0


@pytest.mark.parametrize(
    "condition,state", [("stale", "STALE"), ("cancelled", "CANCELLED"), ("corrupt", "QUARANTINED")]
)
def test_named_reconciliation_never_sends_held_or_cancelled_job_or_touches_another(
    operator_setup, condition, state
):
    setup = operator_setup
    other = setup.control.request_validation(
        setup.teacher,
        setup.document["id"],
        setup.document["version"],
        setup.intent.model_copy(update={"request_id": uuid4()}),
    )
    if condition == "stale":
        setup.control.bridge.service.settings(
            setup.teacher,
            setup.document["id"],
            setup.document["version"],
            setup.document["settings"],
        )
    elif condition == "cancelled":
        setup.coordinator.executor.cancel(setup.teacher, setup.document["id"], str(setup.job_id))
    else:
        with setup.control.repository.connection() as connection:
            connection.execute(
                "UPDATE offline_validation_jobs SET document='broken' WHERE id=?",
                (str(setup.job_id),),
            )
    first = operator.run_once(setup.coordinator, setup.job_id)
    assert first["state"] == state
    assert operator.run_once(setup.coordinator, setup.job_id) == first
    assert setup.queue.send_count == 0
    assert setup.control.jobs.get(other["intent"]["id"]) == other
    if condition == "corrupt":
        with setup.control.repository.connection() as connection:
            assert (
                connection.execute(
                    "SELECT document FROM offline_validation_jobs WHERE id=?", (str(setup.job_id),)
                ).fetchone()[0]
                == "broken"
            )


def test_operator_one_send_per_call_preserves_retry_waits_and_terminal_cap(
    operator_setup, monkeypatch
):
    setup = operator_setup
    setup.queue.failures.extend(["not_accepted"] * 3)
    monkeypatch.setattr("time.sleep", lambda *_args: pytest.fail("The operator must never sleep."))
    delays = [5, 30]
    for number in range(1, 4):
        response = operator.run_once(setup.coordinator, setup.job_id)
        assert response["delivery_sends"] == 1
        assert setup.queue.send_count == number
        if number < 3:
            deadline = setup.coordinator.dispatcher._time(response["next_attempt_at"])
            assert deadline - setup.clock.now == timedelta(seconds=delays[number - 1])
            assert operator.run_once(setup.coordinator, setup.job_id)["delivery_sends"] == 0
            assert setup.queue.send_count == number
            setup.clock.now = deadline
        else:
            assert response["state"] == "DELIVERY_REVIEW"
    assert operator.run_once(setup.coordinator, setup.job_id)["state"] == "DELIVERY_REVIEW"
    assert setup.queue.send_count == 3
    assert setup.control.jobs.get(str(setup.job_id))["execution"]["state"] == "READY"


def test_unknown_enqueue_ack_does_not_authorize_early_validation(operator_setup):
    setup = operator_setup
    setup.queue.failures.append("ack_lost")
    response = operator.run_once(setup.coordinator, setup.job_id)
    assert response["state"] == "DELIVERY_RETRY_WAIT"
    assert len(setup.queue.messages) == 1
    assert setup.control.jobs.get(str(setup.job_id))["execution"]["state"] == "READY"
    setup.clock.now = setup.coordinator.dispatcher._time(response["next_attempt_at"])
    assert operator.run_once(setup.coordinator, setup.job_id)["state"] == "VALIDATED"
    assert len(setup.queue.messages) == 2
    assert setup.queue.send_count == 2


def test_unknown_send_exception_is_redacted_and_live_send_is_not_retried(
    operator_setup, monkeypatch, capsys
):
    setup = operator_setup

    def unknown(_message):
        setup.queue.send_count += 1
        raise RuntimeError("synthetic-private-diagnostic")

    monkeypatch.setattr(setup.queue, "send", unknown)
    monkeypatch.setattr(operator, "SimulatedQueue", lambda: setup.queue)
    assert operator.main(setup.args) == 1
    assert json.loads(capsys.readouterr().out) == {"error": {"code": "OFFLINE_OPERATOR_FAILED"}}
    assert operator.main(setup.args) == 1
    assert json.loads(capsys.readouterr().out) == {"error": {"code": "DELIVERY_IN_FLIGHT"}}
    assert setup.queue.send_count == 1
    delivery = setup.coordinator.dispatcher.status(operator.SYNTHETIC_DISPATCHER, str(setup.job_id))
    assert delivery["state"] == "SENDING"
    assert setup.control.jobs.get(str(setup.job_id))["execution"]["state"] == "READY"


def test_failed_validation_keeps_fence_until_expiry_then_manual_call_recovers(
    operator_setup, monkeypatch
):
    setup = operator_setup
    original = EngineInputValidator.validate

    def interrupted(*_args, **_kwargs):
        raise RuntimeError("Synthetic validation interruption")

    monkeypatch.setattr(EngineInputValidator, "validate", interrupted)
    with pytest.raises(RuntimeError):
        operator.run_once(setup.coordinator, setup.job_id)
    with pytest.raises(ApplicationError) as error:
        operator.run_once(setup.coordinator, setup.job_id)
    assert error.value.code == "JOB_CLAIMED"
    assert setup.queue.send_count == 1
    monkeypatch.setattr(EngineInputValidator, "validate", original)
    setup.clock.now += timedelta(minutes=5)
    response = operator.run_once(setup.coordinator, setup.job_id)
    assert response["state"] == "VALIDATED"
    assert response["delivery_sends"] == 0
    assert setup.control.jobs.get(str(setup.job_id))["execution"]["fence"] == 2


@pytest.mark.parametrize("managed", [False, True])
def test_operator_cannot_take_over_another_worker_assignment(operator_setup, managed):
    setup = operator_setup
    other = Principal(DEVELOPMENT_TENANT_ID, "another-worker", frozenset({"StageWorker"}))
    if managed:
        setup.coordinator.dispatcher.dispatch(
            operator.SYNTHETIC_DISPATCHER,
            str(setup.job_id),
            setup.job["intent"]["message_id"],
            other,
            uuid4(),
        )
    else:
        setup.control.acknowledge_dispatch(
            operator.SYNTHETIC_DISPATCHER,
            str(setup.job_id),
            setup.job["intent"]["message_id"],
            other,
        )
    before = setup.control.jobs.get(str(setup.job_id))
    with pytest.raises(ApplicationError) as error:
        operator.run_once(setup.coordinator, setup.job_id)
    assert error.value.code in ("DISPATCH_CONFLICT", "DISPATCH_ALREADY_ASSIGNED")
    assert setup.control.jobs.get(str(setup.job_id)) == before


def test_named_reconciliation_requires_actual_dispatcher_role(operator_setup):
    setup = operator_setup
    with pytest.raises(ApplicationError) as error:
        OutboxReconciler(setup.control).reconcile_job(setup.teacher, setup.job_id)
    assert error.value.code == "FORBIDDEN"
    assert setup.control.jobs.get(str(setup.job_id)) == setup.job


@pytest.mark.parametrize("symlink", [False, True])
def test_operator_rejects_missing_or_symlink_database_before_initialization(tmp_path, symlink):
    database = tmp_path / "operator.sqlite3"
    target = tmp_path / "target"
    if symlink:
        target.write_text("Synthetic sentinel")
        database.symlink_to(target)
    with pytest.raises(SystemExit) as error:
        operator.main(["--development", "--database", str(database), "--job-id", str(uuid4())])
    assert error.value.code == 2
    if symlink:
        assert target.read_text() == "Synthetic sentinel"
    else:
        assert not database.exists()
