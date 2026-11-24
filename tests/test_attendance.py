import pytest
from conftest import TEACHER, headers, upload
from test_engine_preflight import send_for_review, synthetic_files

pytestmark = pytest.mark.engine


def attendance_files(csv=b"ID,STATUS\n001,present\n002,absent\n", pages=2):
    return {**synthetic_files(pages=pages), "attendance": csv}


def approve(client, response, attendance_confirmed=True):
    return client.post(
        f"/api/exams/{response.json()['id']}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={
            "snapshot_sha256": response.json()["snapshot_sha256"],
            "confirmed": True,
            "attendance_confirmed": attendance_confirmed,
        },
    )


@pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
def test_present_counts_and_distinct_attendance_approval_are_durable(client, service, prefix):
    from handwriting_grader_cloud.repository import SQLiteRepository

    exam_id, _, response = send_for_review(
        client, attendance_files(prefix + b"ID,STATUS\n001,present\n002,absent\n")
    )
    assert response.status_code == 200, response.text
    preflight = response.json()["preflight"]
    assert preflight["summary"]["students"] == 1
    assert preflight["summary"]["absent"] == 1
    assert preflight["summary"]["roster_students"] == 2
    assert preflight["summary"]["pdf_pages"] == 2
    assert preflight["summary"]["attendance_mode"] == "explicit_csv"
    rows = preflight["attendance_review"]
    assert [(row["id"], row["status"]) for row in rows] == [("001", "present"), ("002", "absent")]
    assert "mark" not in rows[1] and "score" not in rows[1]
    result = approve(client, response)
    assert result.status_code == 200
    document = result.json()
    assert document["state"] == "INPUTS_REVIEWED"
    assert len(document["approvals"]) == 2
    input_approval, attendance_approval = document["approvals"]
    assert input_approval["kind"] == "input_review_attestation"
    assert attendance_approval["kind"] == "attendance_review_attestation"
    assert attendance_approval["actor_id"] == "teacher-a"
    assert attendance_approval["attendance_sha256"] == document["artifacts"]["attendance"]["sha256"]
    assert attendance_approval["roster_sha256"] == document["artifacts"]["roster"]["sha256"]
    assert document["current_attendance_approval"] == attendance_approval["id"]
    assert SQLiteRepository(service.repository.path).get(exam_id) == document
    assert approve(client, response).status_code == 409
    assert len(client.get(f"/api/exams/{exam_id}", headers=headers()).json()["approvals"]) == 2


@pytest.mark.parametrize("value, status", [(False, 400), (None, 400), ("true", 422), (1, 422)])
def test_attendance_needs_its_own_literal_confirmation(client, value, status):
    _, _, response = send_for_review(client, attendance_files())
    body = {"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True}
    if value is not None:
        body["attendance_confirmed"] = value
    result = client.post(
        f"/api/exams/{response.json()['id']}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json=body,
    )
    assert result.status_code == status
    assert (
        client.get(f"/api/exams/{response.json()['id']}", headers=headers()).json()["approvals"]
        == []
    )


@pytest.mark.parametrize(
    "csv",
    [
        b"ID,STATUS\n001,present\n",
        b"ID,STATUS\n001,present\n001,absent\n",
        b"ID,STATUS\n001,present\n999,absent\n",
        b"ID,STATUS\n001,present\n002,PRESENT\n",
        b"ID,STATUS\n001,absent\n002,absent\n",
        b"ID,STATUS\n1,present\n002,absent\n",
        b"ID,STATUS\n001 ,present\n002,absent\n",
        b"ID,OTHER\n001,present\n002,absent\n",
        b"ID,STATUS,OTHER\n001,present,x\n002,absent,x\n",
        b"ID,STATUS\n001,present\n002,\n",
        b"\xff",
    ],
)
def test_invalid_attendance_cannot_enter_review(client, csv):
    exam_id, before, response = send_for_review(client, attendance_files(csv))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ATTENDANCE"
    current = client.get(f"/api/exams/{exam_id}", headers=headers())
    assert current.headers["etag"] == before.headers["etag"]
    assert current.json()["state"] == "SETUP"
    assert current.json()["preflight"] is None


def test_pdf_counts_follow_present_students_not_the_full_roster(client):
    _, _, response = send_for_review(client, attendance_files(pages=4))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUTS"


def test_no_csv_preserves_explicit_all_roster_default(client):
    _, _, response = send_for_review(client, synthetic_files())
    assert response.status_code == 200
    preflight = response.json()["preflight"]
    assert preflight["summary"]["attendance_mode"] == "all_roster_students"
    assert preflight["summary"]["students"] == 2
    assert preflight["summary"]["absent"] == 0
    assert all(row["status"] == "present" for row in preflight["attendance_review"])
    result = approve(client, response, attendance_confirmed=False)
    assert result.status_code == 200
    assert len(result.json()["approvals"]) == 1
    assert result.json()["current_attendance_approval"] is None


def test_changed_attendance_invalidates_both_approvals_without_erasing_history(client):
    exam_id, _, response = send_for_review(client, attendance_files())
    result = approve(client, response)
    assert result.status_code == 200
    old_hash = result.json()["snapshot_sha256"]
    changed = upload(
        client,
        exam_id,
        result.headers["etag"],
        "attendance",
        b"ID,STATUS\n001,absent\n002,present\n",
    )
    document = changed.json()
    assert document["state"] == "SETUP"
    assert document["current_approval"] is None
    assert document["current_attendance_approval"] is None
    assert document["preflight"] is None
    assert len(document["approvals"]) == 2
    assert document["snapshot_sha256"] != old_hash
    assert approve(client, response).status_code == 409


def test_corrupt_attendance_after_review_blocks_both_approvals(client, service):
    exam_id, _, response = send_for_review(client, attendance_files())
    artifact = response.json()["artifacts"]["attendance"]["id"]
    with service.repository.connection() as connection:
        connection.execute("UPDATE artifacts SET content=? WHERE id=?", (b"corrupted", artifact))
    result = approve(client, response)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "ARTIFACT_INTEGRITY"
    assert client.get(f"/api/exams/{exam_id}", headers=headers()).json()["approvals"] == []


@pytest.mark.parametrize("identity, status", [("other", 404), ("tenant", 404), ("worker", 403)])
def test_attendance_preview_and_approval_are_exam_scoped(client, identity, status):
    exam_id, _, response = send_for_review(client, attendance_files())
    assert client.get(f"/api/exams/{exam_id}", headers=headers(identity)).status_code == status
    result = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(identity, response.headers["etag"]),
        json={
            "snapshot_sha256": response.json()["snapshot_sha256"],
            "confirmed": True,
            "attendance_confirmed": True,
        },
    )
    assert result.status_code == status


def test_changed_settings_invalidate_both_current_approvals(client):
    exam_id, _, response = send_for_review(client, attendance_files())
    approved = approve(client, response)
    changed = client.put(
        f"/api/exams/{exam_id}/settings",
        headers=headers(etag=approved.headers["etag"]),
        json={**approved.json()["settings"], "pages_per_student": 1},
    )
    assert changed.status_code == 200
    assert changed.json()["current_approval"] is None
    assert changed.json()["current_attendance_approval"] is None
    assert changed.json()["preflight"] is None
    assert len(changed.json()["approvals"]) == 2


def test_wrong_snapshot_with_current_etag_cannot_approve_attendance(client):
    exam_id, _, response = send_for_review(client, attendance_files())
    result = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={
            "snapshot_sha256": "0" * 64,
            "confirmed": True,
            "attendance_confirmed": True,
        },
    )
    assert result.status_code == 409
    assert client.get(f"/api/exams/{exam_id}", headers=headers()).json()["approvals"] == []


def test_concurrent_change_cannot_persist_either_attestation(client, service, monkeypatch):
    exam_id, _, response = send_for_review(client, attendance_files())
    original = service.validator.validate

    def change_during_validation(document, contents):
        validated = original(document, contents)
        service.settings(TEACHER, exam_id, document["version"], document["settings"])
        return validated

    monkeypatch.setattr(service.validator, "validate", change_during_validation)
    result = approve(client, response)
    assert result.status_code == 409
    current = client.get(f"/api/exams/{exam_id}", headers=headers()).json()
    assert current["state"] == "SETUP"
    assert current["approvals"] == []
    assert current["current_approval"] is None
    assert current["current_attendance_approval"] is None
