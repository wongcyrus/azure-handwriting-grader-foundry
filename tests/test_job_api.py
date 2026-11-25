from types import SimpleNamespace
from uuid import uuid4

import pytest
from conftest import TEACHER, WORKER, FakeAuthenticator, headers
from fastapi.testclient import TestClient
from test_jobs import DISPATCHER
from test_workspace import approved_review

from handwriting_grader_cloud.api import create_app
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService

pytestmark = pytest.mark.engine


@pytest.fixture(autouse=True)
def no_paid_actions(monkeypatch):
    from handwriting_grader import attendance, grading, regions, rubric

    def forbidden(*_args, **_kwargs):
        pytest.fail("Teacher job HTTP access must never approve through the engine or grade.")

    for module, name in (
        (grading, "grade_exam"),
        (attendance, "approve_attendance"),
        (regions, "approve_regions"),
        (rubric, "approve_rubric"),
    ):
        monkeypatch.setattr(module, name, forbidden)


@pytest.fixture
def job_api(client, service):
    reviewed = approved_review(client)
    document = reviewed.json()
    exam_id = document["id"]
    etag = reviewed.headers["etag"]
    prepared = client.post(
        f"/api/exams/{exam_id}/offline-inputs",
        headers=headers(etag=etag),
        json={"confirmed": True},
    )
    assert prepared.status_code == 200
    body = {
        "checkpoint_id": prepared.json()["checkpoint_id"],
        "request_id": str(uuid4()),
        "confirmed": True,
    }
    admitted = client.post(f"/api/exams/{exam_id}/jobs", headers=headers(etag=etag), json=body)
    assert admitted.status_code == 201
    return SimpleNamespace(
        client=client,
        service=service,
        document=document,
        exam_id=exam_id,
        etag=etag,
        prepared=prepared,
        body=body,
        job=admitted.json(),
        job_id=admitted.json()["intent"]["id"],
        coordinator=client.app.state.offline_coordinator,
    )


def url(setup, action):
    if action == "prepare":
        return f"/api/exams/{setup.exam_id}/offline-inputs"
    if action == "request":
        return f"/api/exams/{setup.exam_id}/jobs"
    return f"/api/exams/{setup.exam_id}/jobs/{setup.job_id}/cancel"


def body(setup, action):
    return dict(setup.body) if action == "request" else {"confirmed": True}


def test_teacher_http_job_setup_replay_discovery_and_inspection_do_not_execute(
    job_api, monkeypatch
):
    setup = job_api

    def forbidden(*_args, **_kwargs):
        pytest.fail("Teacher HTTP requests must not dispatch or consume.")

    monkeypatch.setattr(setup.coordinator.dispatcher, "dispatch", forbidden)
    monkeypatch.setattr(setup.coordinator, "consume", forbidden)
    monkeypatch.setattr(setup.coordinator.executor, "run", forbidden)
    assert set(setup.prepared.json()) == {"checkpoint_id", "checkpoint_sha256", "exam_version"}
    assert list(setup.coordinator.control.bridge.root.iterdir()) == []
    replay = setup.client.post(
        url(setup, "request"), headers=headers(etag=setup.etag), json=setup.body
    )
    assert replay.status_code == 201
    assert replay.json() == setup.job
    assert replay.headers["etag"] == setup.etag
    listing = setup.client.get(url(setup, "request"), headers=headers())
    assert listing.status_code == 200
    assert listing.json()["next_cursor"] is None
    assert [item["job_id"] for item in listing.json()["items"]] == [setup.job_id]
    status = setup.client.get(f"{url(setup, 'request')}/{setup.job_id}", headers=headers())
    assert status.json()["state"] == "PENDING_DISPATCH"
    assert status.json()["exam_version"] == setup.document["version"]
    assert status.headers["etag"] == setup.etag
    pending = setup.client.get(f"{url(setup, 'request')}/{setup.job_id}/result", headers=headers())
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "RESULT_NOT_READY"
    assert pending.headers["Cache-Control"] == "no-store"
    assert not setup.coordinator.executor.workspace.root.exists()
    assert setup.service.repository.get(setup.exam_id) == setup.document


@pytest.mark.parametrize(
    "identity,expected_status",
    [
        ("other", 404),
        ("tenant", 404),
        ("worker", 403),
        ("admin", 403),
        ("invalid", 401),
    ],
)
def test_all_job_http_routes_remain_owner_teacher_scoped(job_api, identity, expected_status):
    setup = job_api
    for action in ("prepare", "request", "cancel"):
        response = setup.client.post(
            url(setup, action), headers=headers(identity, setup.etag), json=body(setup, action)
        )
        assert response.status_code == expected_status
    for suffix in ("", f"/{setup.job_id}", f"/{setup.job_id}/result"):
        response = setup.client.get(url(setup, "request") + suffix, headers=headers(identity))
        assert response.status_code == expected_status
    assert setup.coordinator.control.jobs.get(setup.job_id)["state"] == "PENDING_DISPATCH"


@pytest.mark.parametrize("action", ["prepare", "request", "cancel"])
@pytest.mark.parametrize("confirmed,expected_status", [(False, 400), (1, 422), ("true", 422)])
def test_offline_http_mutations_require_literal_confirmation(
    job_api, action, confirmed, expected_status
):
    setup = job_api
    payload = body(setup, action)
    payload["confirmed"] = confirmed
    response = setup.client.post(url(setup, action), headers=headers(etag=setup.etag), json=payload)
    assert response.status_code == expected_status
    assert setup.coordinator.control.jobs.get(setup.job_id)["state"] == "PENDING_DISPATCH"


@pytest.mark.parametrize("action", ["prepare", "request", "cancel"])
@pytest.mark.parametrize("etag,expected_status", [(None, 428), ("1", 400), ('"1"', 409)])
def test_offline_http_mutations_require_current_quoted_etag(job_api, action, etag, expected_status):
    setup = job_api
    response = setup.client.post(
        url(setup, action), headers=headers(etag=etag), json=body(setup, action)
    )
    assert response.status_code == expected_status
    assert setup.coordinator.control.jobs.get(setup.job_id)["state"] == "PENDING_DISPATCH"


@pytest.mark.parametrize("action", ["prepare", "request", "cancel"])
@pytest.mark.parametrize(
    "field,value", [("stage", "grade"), ("worker_id", "worker"), ("path", "/private/input")]
)
def test_offline_http_bodies_cannot_select_stage_recipient_or_paths(job_api, action, field, value):
    setup = job_api
    payload = {**body(setup, action), field: value}
    response = setup.client.post(url(setup, action), headers=headers(etag=setup.etag), json=payload)
    assert response.status_code == 422


def test_stale_offline_job_can_be_cancelled_with_current_exam_etag(job_api):
    setup = job_api
    changed = setup.client.put(
        f"/api/exams/{setup.exam_id}/settings",
        headers=headers(etag=setup.etag),
        json=setup.document["settings"],
    )
    assert changed.status_code == 200
    stale = setup.client.get(f"{url(setup, 'request')}/{setup.job_id}", headers=headers())
    assert stale.json()["state"] == "STALE_INPUTS"
    assert stale.json()["source_exam_version"] == setup.document["version"]
    assert stale.headers["etag"] == changed.headers["etag"]
    assert (
        setup.client.post(
            url(setup, "cancel"), headers=headers(etag=setup.etag), json={"confirmed": True}
        ).status_code
        == 409
    )
    cancelled = setup.client.post(
        url(setup, "cancel"),
        headers=headers(etag=changed.headers["etag"]),
        json={"confirmed": True},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"
    replay = setup.client.post(
        url(setup, "cancel"),
        headers=headers(etag=changed.headers["etag"]),
        json={"confirmed": True},
    )
    assert replay.json() == cancelled.json()
    assert setup.service.repository.get(setup.exam_id) == changed.json()


def test_cancellation_rechecks_etag_inside_its_write_transaction(job_api, monkeypatch):
    setup = job_api
    original = setup.coordinator.executor.cancel

    def changed_before_cancel(*args, **kwargs):
        setup.service.settings(
            TEACHER, setup.exam_id, setup.document["version"], setup.document["settings"]
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(setup.coordinator.executor, "cancel", changed_before_cancel)
    response = setup.client.post(
        url(setup, "cancel"), headers=headers(etag=setup.etag), json={"confirmed": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_REVIEW"
    assert setup.coordinator.control.jobs.get(setup.job_id)["state"] == "PENDING_DISPATCH"


def test_job_and_checkpoint_ids_do_not_cross_owned_exam_boundaries(job_api):
    setup = job_api
    other = approved_review(setup.client)
    other_id = other.json()["id"]
    assert setup.client.get(f"/api/exams/{other_id}/jobs", headers=headers()).json()["items"] == []
    assert (
        setup.client.get(
            f"/api/exams/{other_id}/jobs/{setup.job_id}", headers=headers()
        ).status_code
        == 404
    )
    response = setup.client.post(
        f"/api/exams/{other_id}/jobs",
        headers=headers(etag=other.headers["etag"]),
        json={**setup.body, "request_id": str(uuid4())},
    )
    assert response.status_code == 404


def test_owned_job_paging_and_query_validation(job_api):
    setup = job_api
    identifiers = [setup.job_id]
    for _ in range(4):
        response = setup.client.post(
            url(setup, "request"),
            headers=headers(etag=setup.etag),
            json={**setup.body, "request_id": str(uuid4())},
        )
        assert response.status_code == 201
        identifiers.append(response.json()["intent"]["id"])
    cursor = None
    seen = []
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = setup.client.get(url(setup, "request"), headers=headers(), params=params)
        assert page.status_code == 200
        seen.extend(item["job_id"] for item in page.json()["items"])
        cursor = page.json()["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(identifiers)
    for params in ({"limit": 0}, {"limit": 51}, {"cursor": "../outside"}):
        assert (
            setup.client.get(url(setup, "request"), headers=headers(), params=params).status_code
            == 422
        )


def test_verified_and_historical_results_are_readable_without_http_execution(job_api):
    setup = job_api
    coordinator = setup.coordinator
    coordinator.dispatcher.dispatch(
        DISPATCHER, setup.job_id, setup.job["intent"]["message_id"], WORKER, uuid4()
    )
    expected = coordinator.consume(WORKER, coordinator.dispatcher.queue.messages[0], uuid4())
    result = setup.client.get(f"{url(setup, 'request')}/{setup.job_id}/result", headers=headers())
    assert result.status_code == 200
    assert result.json() == expected
    assert result.headers["etag"] == setup.etag
    changed = setup.client.put(
        f"/api/exams/{setup.exam_id}/settings",
        headers=headers(etag=setup.etag),
        json=setup.document["settings"],
    )
    status = setup.client.get(f"{url(setup, 'request')}/{setup.job_id}", headers=headers())
    assert status.json()["state"] == "VALIDATED_HISTORICAL"
    historical = setup.client.get(
        f"{url(setup, 'request')}/{setup.job_id}/result", headers=headers()
    )
    assert historical.json() == expected
    assert historical.headers["etag"] == changed.headers["etag"]
    assert (
        setup.client.post(
            url(setup, "cancel"),
            headers=headers(etag=changed.headers["etag"]),
            json={"confirmed": True},
        ).status_code
        == 409
    )


def test_owner_job_routes_recover_after_api_repository_replacement(job_api):
    setup = job_api
    service = ExamService(SQLiteRepository(setup.service.repository.path))
    with TestClient(create_app(service, FakeAuthenticator())) as restarted:
        page = restarted.get(url(setup, "request"), headers=headers())
        assert page.status_code == 200
        assert page.json()["items"][0]["job_id"] == setup.job_id
        assert page.json()["items"][0]["state"] == "PENDING_DISPATCH"


def test_no_worker_execution_or_paid_http_routes_were_added(job_api):
    setup = job_api
    for action in ("dispatch", "consume", "run", "grade"):
        assert (
            setup.client.post(
                f"{url(setup, 'request')}/{setup.job_id}/{action}",
                headers=headers("worker"),
                json={},
            ).status_code
            == 404
        )
    assert setup.client.get("/health").json()["inference_enabled"] is False
