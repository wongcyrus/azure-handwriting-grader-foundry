import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import ADMIN, OTHER_TEACHER, OTHER_TENANT, TEACHER, WORKER
from test_jobs import DISPATCHER, FOREIGN_WORKER, OTHER_WORKER, dispatch
from test_workspace import approved_review

from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.execution import CLAIM_DURATION, OfflineValidationExecutor
from handwriting_grader_cloud.jobs import OfflineJobControl
from handwriting_grader_cloud.models import OfflineValidationRequest
from handwriting_grader_cloud.preflight import EngineInputValidator
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService
from handwriting_grader_cloud.workspace import WorkspaceBridge

pytestmark = pytest.mark.engine


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 25, tzinfo=UTC)

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def no_grading_or_engine_approval(monkeypatch):
    from handwriting_grader import attendance, grading, regions, rubric

    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline execution must not grade or invent human approval.")

    for module, name in (
        (grading, "grade_exam"),
        (attendance, "approve_attendance"),
        (rubric, "approve_rubric"),
        (regions, "approve_regions"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.fixture
def execution_setup(client, service, tmp_path, request):
    document = approved_review(client, getattr(request, "param", False)).json()
    bridge = WorkspaceBridge(service, tmp_path / "review")
    prepared = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    control = OfflineJobControl(bridge)
    job = control.request_validation(
        TEACHER,
        document["id"],
        document["version"],
        OfflineValidationRequest(
            checkpoint_id=prepared.checkpoint_id, request_id=uuid4(), confirmed=True
        ),
    )
    clock = Clock()
    executor = OfflineValidationExecutor(control, tmp_path / "execution", clock=clock)
    return SimpleNamespace(
        document=document,
        control=control,
        executor=executor,
        job=job,
        job_id=job["intent"]["id"],
        message_id=job["intent"]["message_id"],
        clock=clock,
    )


def run(setup, attempt=None, principal=WORKER):
    return setup.executor.run(principal, setup.job_id, setup.message_id, attempt or uuid4())


def context(setup):
    return setup.control.worker_context(WORKER, setup.job_id, setup.message_id)


def result_count(setup):
    with setup.control.repository.connection() as connection:
        return connection.execute("SELECT count(*) FROM offline_validation_results").fetchone()[0]


def change_inputs(setup):
    document = setup.document
    return setup.control.bridge.service.settings(
        TEACHER, document["id"], document["version"], document["settings"]
    )


@pytest.mark.parametrize("execution_setup", [False, True], indirect=True)
def test_real_readonly_execution_and_immutable_result_survive_restart(
    execution_setup, monkeypatch, tmp_path
):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    original = EngineInputValidator.validate
    calls = []

    def validated(self, document, contents):
        calls.append(document["id"])
        return original(self, document, contents)

    monkeypatch.setattr(EngineInputValidator, "validate", validated)

    def teacher_impersonation(*_args, **_kwargs):
        pytest.fail("Workers must hydrate only their scoped job artifacts.")

    for name in ("hydrate", "prepare_engine_inputs", "restore", "_source"):
        monkeypatch.setattr(WorkspaceBridge, name, teacher_impersonation)
    attempt = uuid4()
    result = run(setup, attempt)
    assert result["status"] == "passed"
    assert result["summary"] == setup.document["preflight"]["summary"]
    assert result["binding"] == setup.job["intent"]["binding"]
    assert result["checkpoint_sha256"] == setup.job["intent"]["checkpoint_sha256"]
    assert list(setup.executor.workspace.root.iterdir()) == []
    assert setup.control.repository.get(setup.document["id"]) == setup.document
    assert result_count(setup) == 1
    assert setup.control.jobs.get(setup.job_id)["state"] == "COMPLETED"
    restarted = OfflineValidationExecutor(
        OfflineJobControl(
            WorkspaceBridge(
                ExamService(SQLiteRepository(setup.control.repository.path)), tmp_path / "recovery"
            )
        ),
        tmp_path / "restarted-execution",
        clock=setup.clock,
    )
    setup.clock.now += timedelta(hours=1)
    assert restarted.run(WORKER, setup.job_id, setup.message_id, uuid4()) == result
    assert restarted.owned_result(TEACHER, setup.document["id"], setup.job_id) == result
    assert calls == [setup.document["id"]]
    assert not restarted.workspace.root.exists()
    with pytest.raises(ApplicationError) as error:
        restarted.cancel(TEACHER, setup.document["id"], setup.job_id)
    assert error.value.code == "JOB_COMPLETED"


def test_live_claim_retries_do_not_restart_or_extend_attempts(execution_setup):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    attempt = uuid4()
    claim = setup.executor.claim(WORKER, setup.job_id, setup.message_id, attempt)
    assert datetime.fromisoformat(claim["expires_at"]) - setup.clock.now == CLAIM_DURATION
    setup.clock.now += timedelta(seconds=20)
    assert setup.executor.claim(WORKER, setup.job_id, setup.message_id, attempt) == claim
    with pytest.raises(ApplicationError) as error:
        run(setup)
    assert error.value.code == "JOB_CLAIMED"
    setup.executor._begin(WORKER, context(setup), claim)
    with pytest.raises(ApplicationError) as error:
        run(setup, attempt)
    assert error.value.code == "JOB_RUNNING"
    assert result_count(setup) == 0
    assert not setup.executor.workspace.root.exists()


def test_expiry_replaces_claim_and_fences_old_completion(execution_setup):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    old = setup.executor.claim(WORKER, setup.job_id, setup.message_id, uuid4())
    captured = context(setup)
    setup.executor._begin(WORKER, captured, old)
    setup.clock.now += CLAIM_DURATION
    with pytest.raises(ApplicationError) as error:
        setup.executor._finish(WORKER, captured, old, {})
    assert error.value.code == "CLAIM_LOST"
    new_attempt = uuid4()
    new = setup.executor.claim(WORKER, setup.job_id, setup.message_id, new_attempt)
    assert new["fence"] == old["fence"] + 1
    with pytest.raises(ApplicationError) as error:
        setup.executor._begin(WORKER, captured, old)
    assert error.value.code == "CLAIM_LOST"
    result = run(setup, new_attempt)
    with pytest.raises(ApplicationError) as error:
        setup.executor._finish(WORKER, captured, old, {"status": "forged"})
    assert error.value.code == "CLAIM_LOST"
    assert setup.executor._finish(WORKER, captured, new, {"status": "overwrite"}) == result
    assert result_count(setup) == 1


@pytest.mark.parametrize("state", ["pending", "claimed", "running"])
def test_teacher_cancellation_revokes_claims_and_pending_delivery_even_when_stale(
    execution_setup, state
):
    setup = execution_setup
    claim = None
    if state != "pending":
        dispatch(setup.control, setup.job)
        claim = setup.executor.claim(WORKER, setup.job_id, setup.message_id, uuid4())
        captured = context(setup)
        if state == "running":
            setup.executor._begin(WORKER, captured, claim)
    change_inputs(setup)
    cancelled = setup.executor.cancel(TEACHER, setup.document["id"], setup.job_id)
    assert cancelled["state"] == "CANCELLED"
    setup.clock.now += CLAIM_DURATION
    assert setup.executor.cancel(TEACHER, setup.document["id"], setup.job_id) == cancelled
    assert setup.control.pending(DISPATCHER) == []
    for action, code in (
        (lambda: run(setup), "NOT_FOUND" if state == "pending" else "JOB_CANCELLED"),
        (lambda: dispatch(setup.control, setup.job), "JOB_CANCELLED"),
    ):
        with pytest.raises(ApplicationError) as error:
            action()
        assert error.value.code == code
    if claim is not None:
        with pytest.raises(ApplicationError) as error:
            setup.executor._finish(WORKER, captured, claim, {})
        assert error.value.status == 409
    assert result_count(setup) == 0


@pytest.mark.parametrize(
    "principal,status",
    [(TEACHER, 403), (ADMIN, 403), (OTHER_WORKER, 404), (FOREIGN_WORKER, 404)],
)
def test_execution_claim_cannot_cross_worker_roles_or_assignments(
    execution_setup, principal, status
):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    with pytest.raises(ApplicationError) as error:
        run(setup, principal=principal)
    assert error.value.status == status
    assert setup.control.jobs.get(setup.job_id)["execution"]["state"] == "READY"
    assert result_count(setup) == 0


@pytest.mark.parametrize(
    "principal,status",
    [(WORKER, 403), (ADMIN, 403), (OTHER_TEACHER, 404), (OTHER_TENANT, 404)],
)
def test_cancellation_and_historical_results_remain_teacher_owned(
    execution_setup, principal, status
):
    setup = execution_setup
    for action in (
        lambda: setup.executor.cancel(principal, setup.document["id"], setup.job_id),
        lambda: setup.executor.owned_result(principal, setup.document["id"], setup.job_id),
    ):
        with pytest.raises(ApplicationError) as error:
            action()
        assert error.value.status == status
    assert setup.control.jobs.get(setup.job_id)["state"] == "PENDING_DISPATCH"


def test_attempt_ids_messages_and_caller_lease_fields_are_not_authority(execution_setup):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    for attempt, message, code in (
        ("../unsafe", setup.message_id, "INVALID_ATTEMPT"),
        (uuid4(), str(uuid4()), "NOT_FOUND"),
    ):
        with pytest.raises(ApplicationError) as error:
            setup.executor.claim(WORKER, setup.job_id, message, attempt)
        assert error.value.code == code
    claim = setup.executor.claim(WORKER, setup.job_id, setup.message_id, uuid4())
    for key, value in (
        ("fence", claim["fence"] + 1),
        ("attempt_id", str(uuid4())),
        ("expires_at", (setup.clock.now + timedelta(days=1)).isoformat()),
    ):
        with pytest.raises(ApplicationError) as error:
            setup.executor._begin(WORKER, context(setup), {**claim, key: value})
        assert error.value.code == "CLAIM_LOST"
    assert setup.control.jobs.get(setup.job_id)["execution"] == claim


@pytest.mark.parametrize("during_validation", ["cancel", "stale", "expire"])
def test_late_validation_cannot_publish_after_cancellation_change_or_expiry(
    execution_setup, monkeypatch, during_validation
):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    original = EngineInputValidator.validate

    def interrupted(self, document, contents):
        result = original(self, document, contents)
        if during_validation == "cancel":
            setup.executor.cancel(TEACHER, setup.document["id"], setup.job_id)
        elif during_validation == "stale":
            change_inputs(setup)
        else:
            setup.clock.now += CLAIM_DURATION
        return result

    monkeypatch.setattr(EngineInputValidator, "validate", interrupted)
    with pytest.raises(ApplicationError) as error:
        run(setup)
    assert (
        error.value.code
        == {
            "cancel": "JOB_CANCELLED",
            "stale": "STALE_REVIEW",
            "expire": "CLAIM_LOST",
        }[during_validation]
    )
    assert result_count(setup) == 0
    assert list(setup.executor.workspace.root.iterdir()) == []


def test_replacement_can_finish_before_expired_original_returns(execution_setup, monkeypatch):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    original = EngineInputValidator.validate
    completed = []

    def replaced(self, document, contents):
        preflight = original(self, document, contents)
        if not completed:
            completed.append(None)
            setup.clock.now += CLAIM_DURATION
            completed[0] = run(setup)
        return preflight

    monkeypatch.setattr(EngineInputValidator, "validate", replaced)
    with pytest.raises(ApplicationError) as error:
        run(setup)
    assert error.value.code == "CLAIM_LOST"
    assert setup.executor.owned_result(TEACHER, setup.document["id"], setup.job_id) == completed[0]
    assert result_count(setup) == 1
    assert list(setup.executor.workspace.root.iterdir()) == []


def test_result_insert_and_completion_are_atomic_and_retry_after_crash(execution_setup):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    with setup.control.repository.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_completion BEFORE UPDATE ON offline_job_execution "
            "WHEN json_extract(NEW.document, '$.state')='COMPLETED' "
            "BEGIN SELECT RAISE(ABORT, 'synthetic crash before completion'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        run(setup)
    assert setup.control.jobs.get(setup.job_id)["state"] == "RUNNING"
    assert result_count(setup) == 0
    assert list(setup.executor.workspace.root.iterdir()) == []
    with setup.control.repository.connection() as connection:
        connection.execute("DROP TRIGGER fail_completion")
    setup.clock.now += CLAIM_DURATION
    assert run(setup)["status"] == "passed"
    assert setup.control.jobs.get(setup.job_id)["execution"]["fence"] == 2
    assert result_count(setup) == 1


def test_competing_process_attempts_sharing_identity_have_only_one_live_claim(
    execution_setup, monkeypatch
):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    original = setup.control.worker_context
    barrier = Barrier(2)

    def simultaneous_read(*args):
        granted = original(*args)
        barrier.wait(timeout=10)
        return granted

    monkeypatch.setattr(setup.control, "worker_context", simultaneous_read)

    def acquire(_index):
        try:
            return setup.executor.claim(WORKER, setup.job_id, setup.message_id, uuid4())["state"]
        except ApplicationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(acquire, range(2)))
    assert sorted(outcomes) == ["CLAIMED", "JOB_CLAIMED"]
    assert setup.control.jobs.get(setup.job_id)["execution"]["fence"] == 1


def test_claim_survives_repository_replacement_without_extending_expiry(execution_setup, tmp_path):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    attempt = uuid4()
    claim = setup.executor.claim(WORKER, setup.job_id, setup.message_id, attempt)
    replacement = OfflineValidationExecutor(
        OfflineJobControl(
            WorkspaceBridge(
                ExamService(SQLiteRepository(setup.control.repository.path)), tmp_path / "recovery"
            )
        ),
        tmp_path / "restarted",
        clock=setup.clock,
    )
    setup.clock.now += timedelta(seconds=10)
    assert replacement.claim(WORKER, setup.job_id, setup.message_id, attempt) == claim
    with pytest.raises(ApplicationError) as error:
        replacement.claim(WORKER, setup.job_id, setup.message_id, uuid4())
    assert error.value.code == "JOB_CLAIMED"
    setup.clock.now = datetime.fromisoformat(claim["expires_at"])
    assert replacement.run(WORKER, setup.job_id, setup.message_id, uuid4())["status"] == "passed"
    assert setup.control.jobs.get(setup.job_id)["execution"]["fence"] == claim["fence"] + 1


@pytest.mark.parametrize("phase", ["before", "after"])
def test_changed_engine_pin_blocks_validation_publication(execution_setup, monkeypatch, phase):
    from handwriting_grader_cloud import preflight

    setup = execution_setup
    dispatch(setup.control, setup.job)
    if phase == "before":
        monkeypatch.setattr(preflight, "ENGINE_COMMIT", "unapproved-engine-pin")
    else:
        original = EngineInputValidator.validate

        def changed_after_validation(self, document, contents):
            result = original(self, document, contents)
            monkeypatch.setattr(preflight, "ENGINE_COMMIT", "unapproved-engine-pin")
            return result

        monkeypatch.setattr(EngineInputValidator, "validate", changed_after_validation)
    with pytest.raises(ApplicationError) as error:
        run(setup)
    assert error.value.code == "ENGINE_PIN_MISMATCH"
    assert result_count(setup) == 0
    assert list(setup.executor.workspace.root.iterdir()) == []


def test_expiry_during_result_transaction_rolls_back_publication(execution_setup):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    claim = setup.executor.claim(WORKER, setup.job_id, setup.message_id, uuid4())
    captured = context(setup)
    setup.executor._begin(WORKER, captured, claim)
    deadline = datetime.fromisoformat(claim["expires_at"])
    times = iter([deadline - timedelta(microseconds=1), deadline])
    setup.executor.clock = lambda: next(times)
    with pytest.raises(ApplicationError) as error:
        setup.executor._finish(WORKER, captured, claim, {})
    assert error.value.code == "CLAIM_LOST"
    assert result_count(setup) == 0
    assert setup.control.jobs.get(setup.job_id)["state"] == "RUNNING"


def test_corrupt_scoped_artifact_prevents_execution_result(execution_setup):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    artifact_id = context(setup)["checkpoint"]["files"]["inputs/roster.xlsx"]["artifact_id"]
    with setup.control.repository.connection() as connection:
        connection.execute("UPDATE artifacts SET content=? WHERE id=?", (b"corrupt", artifact_id))
    with pytest.raises(ApplicationError) as error:
        run(setup)
    assert error.value.code == "JOB_INTEGRITY"
    assert result_count(setup) == 0
    assert not setup.executor.workspace.root.exists()


def test_completed_result_is_integrity_checked_and_remains_historical(execution_setup):
    setup = execution_setup
    dispatch(setup.control, setup.job)
    result = run(setup)
    change_inputs(setup)
    assert setup.executor.owned_result(TEACHER, setup.document["id"], setup.job_id) == result
    with pytest.raises(ApplicationError) as error:
        run(setup)
    assert error.value.code == "STALE_JOB"
    result["stage"] = "grade"
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    with setup.control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_validation_results SET document=?, sha256=? WHERE job_id=?",
            (encoded, digest, setup.job_id),
        )
        execution = setup.control.jobs.get(setup.job_id)["execution"]
        setup.executor._save(connection, setup.job_id, {**execution, "result_sha256": digest})
    with pytest.raises(ApplicationError) as error:
        setup.executor.owned_result(TEACHER, setup.document["id"], setup.job_id)
    assert error.value.code == "JOB_INTEGRITY"
