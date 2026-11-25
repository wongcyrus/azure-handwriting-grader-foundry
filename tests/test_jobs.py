import hashlib
import json
import sqlite3
from uuid import UUID, uuid4

import pytest
from conftest import ADMIN, OTHER_TEACHER, OTHER_TENANT, TEACHER, WORKER
from pydantic import ValidationError
from test_workspace import approved_review

from handwriting_grader_cloud.auth import Principal
from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.jobs import OFFLINE_STAGE, OfflineJobControl
from handwriting_grader_cloud.models import OfflineValidationRequest
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService
from handwriting_grader_cloud.workspace import WorkspaceBridge

pytestmark = pytest.mark.engine
DISPATCHER = Principal("school-a", "dispatcher-a", frozenset({"JobDispatcher"}))
OTHER_DISPATCHER = Principal("school-b", "dispatcher-b", frozenset({"JobDispatcher"}))
OTHER_WORKER = Principal("school-a", "worker-b", frozenset({"StageWorker"}))
FOREIGN_WORKER = Principal("school-b", "worker", frozenset({"StageWorker"}))


@pytest.fixture(autouse=True)
def no_grading_execution(monkeypatch):
    from handwriting_grader import grading

    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline job control must not execute grading.")

    monkeypatch.setattr(grading, "grade_exam", forbidden)


@pytest.fixture
def setup_job(client, service, tmp_path):
    document = approved_review(client).json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    prepared = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    control = OfflineJobControl(bridge)
    request = OfflineValidationRequest(
        checkpoint_id=UUID(prepared.checkpoint_id), request_id=uuid4(), confirmed=True
    )
    return document, control, request


def admit(setup):
    document, control, request = setup
    return control.request_validation(TEACHER, document["id"], document["version"], request)


def dispatch(control, job, worker=WORKER):
    return control.acknowledge_dispatch(
        DISPATCHER, job["intent"]["id"], job["intent"]["message_id"], worker
    )


def row_counts(control):
    with control.repository.connection() as connection:
        return (
            connection.execute("SELECT count(*) FROM offline_validation_jobs").fetchone()[0],
            connection.execute("SELECT count(*) FROM offline_job_outbox").fetchone()[0],
        )


@pytest.mark.parametrize("attendance", [False, True])
def test_explicit_offline_job_and_outbox_survive_restart_without_execution(
    client, service, tmp_path, attendance
):
    document = approved_review(client, attendance).json()
    bridge = WorkspaceBridge(service, tmp_path / "workspaces")
    prepared = bridge.prepare_engine_inputs(TEACHER, document["id"], document["version"])
    control = OfflineJobControl(bridge)
    request = OfflineValidationRequest(
        checkpoint_id=prepared.checkpoint_id, request_id=uuid4(), confirmed=True
    )
    paths = set(bridge.root.iterdir())
    job = control.request_validation(TEACHER, document["id"], document["version"], request)
    assert job["state"] == "PENDING_DISPATCH"
    assert job["intent"]["stage"] == OFFLINE_STAGE
    assert control.pending(DISPATCHER) == [
        {"job_id": job["intent"]["id"], "message_id": job["intent"]["message_id"]}
    ]
    assert row_counts(control) == (1, 1)
    assert service.repository.get(document["id"]) == document
    assert set(bridge.root.iterdir()) == paths
    replacement = OfflineJobControl(
        WorkspaceBridge(
            ExamService(SQLiteRepository(service.repository.path)), tmp_path / "replacement"
        )
    )
    assert replacement.owned_job(TEACHER, document["id"], job["intent"]["id"]) == job
    granted = dispatch(replacement, job)
    assert granted["state"] == "DISPATCHED"
    assert granted["intent"] == job["intent"]
    context = replacement.worker_context(WORKER, job["intent"]["id"], job["intent"]["message_id"])
    assert context["stage"] == OFFLINE_STAGE
    assert context["binding"]["approval_ids"]["inputs"] == document["current_approval"]
    assert replacement.pending(DISPATCHER) == []
    reference = context["checkpoint"]["files"]["inputs/roster.xlsx"]
    content = replacement.worker_artifact(
        WORKER, job["intent"]["id"], job["intent"]["message_id"], reference["artifact_id"]
    )
    assert hashlib.sha256(content).hexdigest() == reference["sha256"]
    assert row_counts(replacement) == (1, 1)
    assert service.repository.get(document["id"]) == document
    assert not (tmp_path / "replacement").exists()


def test_repeated_request_and_duplicate_dispatch_keep_one_stable_job(setup_job):
    document, control, request = setup_job
    first = admit(setup_job)
    assert admit(setup_job) == first
    second_checkpoint = control.bridge.prepare_engine_inputs(
        TEACHER, document["id"], document["version"]
    )
    changed = request.model_copy(update={"checkpoint_id": UUID(second_checkpoint.checkpoint_id)})
    with pytest.raises(ApplicationError) as error:
        control.request_validation(TEACHER, document["id"], document["version"], changed)
    assert error.value.code == "REQUEST_CONFLICT"
    granted = dispatch(control, first)
    assert dispatch(control, first) == granted
    assert admit(setup_job) == granted
    assert row_counts(control) == (1, 1)
    with pytest.raises(ApplicationError) as error:
        dispatch(control, first, OTHER_WORKER)
    assert error.value.code == "DISPATCH_CONFLICT"
    assert control.jobs.get(first["intent"]["id"]) == granted


@pytest.mark.parametrize(
    "field,value", [("stage", "grade"), ("worker_id", "worker"), ("confirmed", 1)]
)
def test_request_model_cannot_select_paid_stage_or_worker(setup_job, field, value):
    _, _, request = setup_job
    body = request.model_dump(mode="json")
    body[field] = value
    with pytest.raises(ValidationError):
        OfflineValidationRequest.model_validate(body)


def test_false_confirmation_and_review_only_checkpoint_do_not_admit_jobs(setup_job):
    document, control, request = setup_job
    with pytest.raises(ApplicationError) as error:
        control.request_validation(
            TEACHER,
            document["id"],
            document["version"],
            request.model_copy(update={"confirmed": False}),
        )
    assert error.value.code == "REQUEST_REQUIRED"
    review = control.bridge.hydrate(TEACHER, document["id"], document["version"])
    with pytest.raises(ApplicationError) as error:
        control.request_validation(
            TEACHER,
            document["id"],
            document["version"],
            request.model_copy(update={"checkpoint_id": UUID(review.checkpoint_id)}),
        )
    assert error.value.code == "ENGINE_INPUTS_REQUIRED"
    assert row_counts(control) == (0, 0)


@pytest.mark.parametrize(
    "principal,status",
    [(OTHER_TEACHER, 404), (OTHER_TENANT, 404), (WORKER, 403), (ADMIN, 403)],
)
def test_job_request_and_owner_read_are_teacher_scoped(setup_job, principal, status):
    document, control, request = setup_job
    job = admit(setup_job)
    for action in (
        lambda: control.request_validation(principal, document["id"], document["version"], request),
        lambda: control.owned_job(principal, document["id"], job["intent"]["id"]),
    ):
        with pytest.raises(ApplicationError) as error:
            action()
        assert error.value.status == status
    assert row_counts(control) == (1, 1)


def test_checkpoint_and_job_ids_cannot_cross_owned_exam_boundaries(client, setup_job):
    document, control, request = setup_job
    job = admit(setup_job)
    other = approved_review(client).json()
    checkpoint = control.bridge.prepare_engine_inputs(TEACHER, other["id"], other["version"])
    with pytest.raises(ApplicationError) as error:
        control.request_validation(
            TEACHER,
            document["id"],
            document["version"],
            request.model_copy(update={"checkpoint_id": UUID(checkpoint.checkpoint_id)}),
        )
    assert error.value.status == 404
    with pytest.raises(ApplicationError) as error:
        control.owned_job(TEACHER, other["id"], job["intent"]["id"])
    assert error.value.status == 404
    assert row_counts(control) == (1, 1)


def test_dispatch_and_worker_grants_do_not_cross_roles_tenants_or_messages(setup_job):
    _, control, _ = setup_job
    job = admit(setup_job)
    job_id, message_id = job["intent"]["id"], job["intent"]["message_id"]
    assert control.pending(OTHER_DISPATCHER) == []
    for principal in (TEACHER, WORKER, ADMIN):
        with pytest.raises(ApplicationError) as error:
            control.pending(principal)
        assert error.value.status == 403
    for dispatcher, worker, message in (
        (OTHER_DISPATCHER, WORKER, message_id),
        (DISPATCHER, FOREIGN_WORKER, message_id),
        (DISPATCHER, WORKER, str(uuid4())),
    ):
        with pytest.raises(ApplicationError) as error:
            control.acknowledge_dispatch(dispatcher, job_id, message, worker)
        assert error.value.status == 404
    with pytest.raises(ApplicationError) as error:
        control.acknowledge_dispatch(DISPATCHER, job_id, message_id, TEACHER)
    assert error.value.status == 403
    with pytest.raises(ApplicationError):
        control.worker_context(WORKER, job_id, message_id)
    dispatch(control, job)
    for principal, message in (
        (OTHER_WORKER, message_id),
        (FOREIGN_WORKER, message_id),
        (WORKER, str(uuid4())),
    ):
        with pytest.raises(ApplicationError) as error:
            control.worker_context(principal, job_id, message)
        assert error.value.status == 404


def test_worker_artifact_grant_excludes_other_files_and_checks_corruption(setup_job):
    document, control, _ = setup_job
    job = admit(setup_job)
    dispatch(control, job)
    unrelated = str(uuid4())
    control.repository.save(
        document, document["version"], artifact=(unrelated, b"synthetic ungranted artifact")
    )
    with pytest.raises(ApplicationError) as error:
        control.worker_artifact(WORKER, job["intent"]["id"], job["intent"]["message_id"], unrelated)
    assert error.value.status == 404
    context = control.worker_context(WORKER, job["intent"]["id"], job["intent"]["message_id"])
    reference = context["checkpoint"]["files"]["inputs/roster.xlsx"]
    with control.repository.connection() as connection:
        connection.execute(
            "UPDATE artifacts SET content=? WHERE id=?", (b"corrupt", reference["artifact_id"])
        )
    with pytest.raises(ApplicationError) as error:
        control.worker_artifact(
            WORKER, job["intent"]["id"], job["intent"]["message_id"], reference["artifact_id"]
        )
    assert error.value.code == "JOB_INTEGRITY"


def test_input_changes_revoke_dispatch_context_and_idempotent_replay(setup_job):
    document, control, request = setup_job
    job = admit(setup_job)
    dispatch(control, job)
    current = control.bridge.service.settings(
        TEACHER, document["id"], document["version"], document["settings"]
    )
    for action in (
        lambda: dispatch(control, job),
        lambda: control.worker_context(WORKER, job["intent"]["id"], job["intent"]["message_id"]),
        lambda: control.request_validation(TEACHER, document["id"], current["version"], request),
    ):
        with pytest.raises(ApplicationError) as error:
            action()
        assert error.value.status == 409
    assert row_counts(control) == (1, 1)


def test_worker_context_rechecks_version_after_loading_its_grant(setup_job, monkeypatch):
    document, control, _ = setup_job
    job = admit(setup_job)
    dispatch(control, job)
    original = control._current

    def changed_after_context_read(job):
        checkpoint = original(job)
        control.bridge.service.settings(
            TEACHER, document["id"], document["version"], document["settings"]
        )
        return checkpoint

    monkeypatch.setattr(control, "_current", changed_after_context_read)
    with pytest.raises(ApplicationError) as error:
        control.worker_context(WORKER, job["intent"]["id"], job["intent"]["message_id"])
    assert error.value.code == "STALE_REVIEW"
    assert row_counts(control) == (1, 1)


def test_job_and_outbox_admission_race_rolls_back_both_rows(setup_job, monkeypatch):
    document, control, _ = setup_job
    original = control.jobs.admit

    def changed_before_admission(intent):
        control.bridge.service.settings(
            TEACHER, document["id"], document["version"], document["settings"]
        )
        return original(intent)

    monkeypatch.setattr(control.jobs, "admit", changed_before_admission)
    with pytest.raises(ApplicationError) as error:
        admit(setup_job)
    assert error.value.code == "STALE_REVIEW"
    assert row_counts(control) == (0, 0)


def test_outbox_insert_failure_rolls_back_the_new_job(setup_job, monkeypatch):
    from handwriting_grader_cloud import jobs

    document, control, request = setup_job
    first = admit(setup_job)
    original = jobs.uuid4
    values = iter([original(), UUID(first["intent"]["message_id"])])
    monkeypatch.setattr(jobs, "uuid4", lambda: next(values))
    with pytest.raises(sqlite3.IntegrityError):
        control.request_validation(
            TEACHER,
            document["id"],
            document["version"],
            request.model_copy(update={"request_id": uuid4()}),
        )
    assert row_counts(control) == (1, 1)
    assert control.jobs.get(first["intent"]["id"]) == first


@pytest.mark.parametrize("change", ["hash", "stage"])
def test_job_corruption_or_rehashed_paid_stage_cannot_grant_context(setup_job, change):
    _, control, _ = setup_job
    job = admit(setup_job)
    dispatch(control, job)
    intent = job["intent"]
    intent["stage"] = "grade"
    encoded = json.dumps(intent, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode()).hexdigest() if change == "stage" else "0" * 64
    with control.repository.connection() as connection:
        connection.execute(
            "UPDATE offline_validation_jobs SET document=?, sha256=? WHERE id=?",
            (encoded, digest, intent["id"]),
        )
    with pytest.raises(ApplicationError) as error:
        control.worker_context(WORKER, intent["id"], intent["message_id"])
    assert error.value.status == 409


@pytest.mark.parametrize("limit", [0, 51, True, "20"])
def test_dispatch_outbox_limits_are_strictly_bounded(setup_job, limit):
    _, control, _ = setup_job
    with pytest.raises(ApplicationError) as error:
        control.pending(DISPATCHER, limit)
    assert error.value.code == "INVALID_LIMIT"
