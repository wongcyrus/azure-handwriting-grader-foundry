import hashlib

import pytest
from conftest import create, headers, ready, upload

from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService


def test_review_survives_restart_and_records_authenticated_identity(client, service):
    response = ready(client)
    exam_id = response.json()["id"]
    reviewed_hash = response.json()["snapshot_sha256"]
    response = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": reviewed_hash, "confirmed": True},
    )
    assert response.status_code == 200
    document = response.json()
    assert document["state"] == "INPUTS_REVIEWED"
    assert document["approvals"][0]["actor_id"] == "teacher-a"
    assert document["approvals"][0]["snapshot_sha256"] == reviewed_hash
    restarted = ExamService(SQLiteRepository(service.repository.path))
    assert restarted.repository.get(exam_id) == document


@pytest.mark.parametrize(
    "identity, status",
    [("other", 404), ("tenant", 404), ("worker", 403), ("admin", 403), ("invalid", 401)],
)
def test_exam_access_and_approval_are_scoped(client, identity, status):
    response = ready(client)
    exam_id = response.json()["id"]
    assert client.get(f"/api/exams/{exam_id}", headers=headers(identity)).status_code == status
    response = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(identity, response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    assert response.status_code == status


def test_missing_authentication_and_forged_identity_are_rejected(client):
    assert client.post("/api/exams", json={}).status_code == 401
    response = client.post(
        "/api/exams",
        headers=headers(),
        json={"title": "Exam", "settings": {"pages_per_student": 2}, "owner_id": "victim"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "etag, status",
    [(None, 428), ('"0"', 400), ("1", 400), ('"999999999999999999999999"', 400), ('"2"', 409)],
)
def test_mutations_require_current_bounded_etag(client, etag, status):
    response = create(client)
    exam_id = response.json()["id"]
    result = client.post(f"/api/exams/{exam_id}/review", headers=headers(etag=etag))
    assert result.status_code == status
    assert client.get(f"/api/exams/{exam_id}", headers=headers()).headers["etag"] == '"1"'


def test_missing_inputs_and_scan_confirmation_block_review(client):
    response = create(client, confirmed=False)
    exam_id = response.json()["id"]
    result = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    assert result.json()["error"]["code"] == "MISSING_INPUTS"
    for kind in ("scans", "roster", "rubric"):
        response = upload(client, exam_id, response.headers["etag"], kind)
    result = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    assert result.json()["error"]["code"] == "LAYOUT_CONFIRMATION_REQUIRED"


@pytest.mark.parametrize("confirmed", [False, "true", 1])
def test_approval_requires_literal_confirmation(client, confirmed):
    response = ready(client)
    result = client.post(
        f"/api/exams/{response.json()['id']}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": confirmed},
    )
    assert result.status_code == (400 if confirmed is False else 422)


def test_wrong_snapshot_and_unreviewed_state_cannot_be_approved(client):
    response = ready(client)
    result = client.post(
        f"/api/exams/{response.json()['id']}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": "a" * 64, "confirmed": True},
    )
    assert result.status_code == 409
    setup = create(client)
    result = client.post(
        f"/api/exams/{setup.json()['id']}/approvals",
        headers=headers(etag=setup.headers["etag"]),
        json={"snapshot_sha256": setup.json()["snapshot_sha256"], "confirmed": True},
    )
    assert result.status_code == 409


def test_changed_inputs_invalidate_approval_but_keep_old_content_and_history(client):
    response = ready(client)
    exam_id = response.json()["id"]
    old_artifact = response.json()["artifacts"]["scans"]["id"]
    response = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    old_hash = response.json()["snapshot_sha256"]
    response = upload(client, exam_id, response.headers["etag"], "scans", b"new synthetic bytes")
    document = response.json()
    assert document["state"] == "SETUP"
    assert document["current_approval"] is None
    assert len(document["approvals"]) == 1
    assert document["snapshot_sha256"] != old_hash
    assert (
        document["artifacts"]["scans"]["sha256"]
        == hashlib.sha256(b"new synthetic bytes").hexdigest()
    )
    download = client.get(f"/api/exams/{exam_id}/artifacts/{old_artifact}", headers=headers())
    assert download.content == b"synthetic input fixture"
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["content-disposition"].startswith("attachment;")


def test_layout_changes_invalidate_review(client):
    response = ready(client)
    result = client.put(
        f"/api/exams/{response.json()['id']}/settings",
        headers=headers(etag=response.headers["etag"]),
        json={"pages_per_student": 3, "scan_order_confirmed": True},
    )
    assert result.status_code == 200
    assert result.json()["state"] == "SETUP"
    assert result.json()["snapshot_sha256"] != response.json()["snapshot_sha256"]


def test_stale_tab_cannot_overwrite_or_duplicate_approval(client):
    response = ready(client)
    exam_id = response.json()["id"]
    etag = response.headers["etag"]
    request = {"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True}
    first = client.post(f"/api/exams/{exam_id}/approvals", headers=headers(etag=etag), json=request)
    second = client.post(
        f"/api/exams/{exam_id}/approvals", headers=headers(etag=etag), json=request
    )
    assert first.status_code == 200
    assert second.status_code == 409
    assert len(client.get(f"/api/exams/{exam_id}", headers=headers()).json()["approvals"]) == 1


def test_artifact_access_does_not_cross_exam_or_owner(client):
    response = ready(client)
    exam_id = response.json()["id"]
    artifact_id = response.json()["artifacts"]["scans"]["id"]
    other_exam = create(client).json()["id"]
    assert (
        client.get(
            f"/api/exams/{exam_id}/artifacts/{artifact_id}", headers=headers("other")
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/exams/{other_exam}/artifacts/{artifact_id}", headers=headers()
        ).status_code
        == 404
    )


def test_oversize_empty_and_invalid_kind_uploads_do_not_change_state(client, monkeypatch):
    import handwriting_grader_cloud.api as api

    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 4)
    response = create(client)
    path = f"/api/exams/{response.json()['id']}/artifacts/"
    upload_headers = {
        **headers(etag=response.headers["etag"]),
        "Content-Type": "application/octet-stream",
    }
    assert client.post(path + "scans", headers=upload_headers, content=b"12345").status_code == 413
    assert client.post(path + "scans", headers=upload_headers, content=b"").status_code == 400
    assert client.post(path + "script", headers=upload_headers, content=b"12").status_code == 422
    assert (
        client.get(f"/api/exams/{response.json()['id']}", headers=headers()).headers["etag"]
        == response.headers["etag"]
    )


@pytest.mark.parametrize("value", [True, 0, -1, 21, "2"])
def test_layout_counts_are_bounded_integers(client, value):
    response = client.post(
        "/api/exams",
        headers=headers(),
        json={"title": "Synthetic exam", "settings": {"pages_per_student": value}},
    )
    assert response.status_code == 422


def test_no_paid_or_grading_endpoint_exists(client):
    response = create(client)
    assert (
        client.post(f"/api/exams/{response.json()['id']}/grade", headers=headers()).status_code
        == 404
    )
    assert client.get("/health").json()["inference_enabled"] is False
