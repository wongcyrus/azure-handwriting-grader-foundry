import json
from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace

import pytest
from conftest import create, headers, ready, upload

from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.preflight import EngineInputValidator, engine_functions


def test_validation_failure_does_not_enter_review(client, service):
    class RejectInputs:
        def validate(self, document, contents):
            raise ApplicationError("INVALID_INPUTS", "Invalid inputs.", details=["Fix the layout."])

    service.validator = RejectInputs()
    response = create(client)
    exam_id = response.json()["id"]
    for kind in ("scans", "roster", "rubric"):
        response = upload(client, exam_id, response.headers["etag"], kind)
    result = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    assert result.status_code == 400
    assert result.json()["error"]["details"] == ["Fix the layout."]
    current = client.get(f"/api/exams/{exam_id}", headers=headers())
    assert current.headers["etag"] == response.headers["etag"]
    assert current.json()["state"] == "SETUP"
    assert current.json()["preflight"] is None


def test_approval_revalidates_instead_of_trusting_saved_preflight(client, service):
    response = ready(client)

    class RejectOnApproval:
        def validate(self, document, contents):
            raise ApplicationError("INVALID_INPUTS", "Revalidation failed.")

    service.validator = RejectOnApproval()
    exam_id = response.json()["id"]
    result = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    assert result.status_code == 400
    current = client.get(f"/api/exams/{exam_id}", headers=headers())
    assert current.headers["etag"] == response.headers["etag"]
    assert current.json()["state"] == "WAITING_FOR_INPUT_REVIEW"
    assert current.json()["approvals"] == []


def test_corrupt_stored_bytes_block_approval(client, service):
    response = ready(client)
    exam_id = response.json()["id"]
    artifact = response.json()["artifacts"]["scans"]["id"]
    with service.repository.connection() as connection:
        connection.execute("UPDATE artifacts SET content=? WHERE id=?", (b"corrupted", artifact))
    result = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "ARTIFACT_INTEGRITY"


def test_legacy_review_without_preflight_cannot_be_approved(client, service):
    response = ready(client)
    document = response.json()
    document["preflight"] = None
    document["version"] += 1
    service.repository.save(document, response.json()["version"])
    result = client.post(
        f"/api/exams/{document['id']}/approvals",
        headers=headers(etag=f'"{document["version"]}"'),
        json={"snapshot_sha256": document["snapshot_sha256"], "confirmed": True},
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "PREFLIGHT_REQUIRED"


def test_missing_engine_fails_closed_before_parsing(client, service, monkeypatch):
    import handwriting_grader_cloud.preflight as preflight

    def missing(_name):
        raise PackageNotFoundError("synthetic missing engine")

    monkeypatch.setattr(preflight, "distribution", missing)
    service.validator = EngineInputValidator()
    response = create(client)
    exam_id = response.json()["id"]
    for kind in ("scans", "roster", "rubric"):
        response = upload(client, exam_id, response.headers["etag"], kind)
    result = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "ENGINE_UNAVAILABLE"
    assert client.get(f"/api/exams/{exam_id}", headers=headers()).json()["state"] == "SETUP"


@pytest.mark.parametrize(
    "source",
    ["invalid json", "[]", "{}", json.dumps({"vcs_info": {"commit_id": "different-commit"}})],
)
def test_missing_or_changed_engine_provenance_is_rejected(monkeypatch, source):
    import handwriting_grader_cloud.preflight as preflight

    monkeypatch.setattr(
        preflight, "distribution", lambda _name: SimpleNamespace(read_text=lambda _file: source)
    )
    with pytest.raises(ApplicationError) as error:
        engine_functions()
    assert error.value.status == 503
    assert error.value.code == "ENGINE_PIN_MISMATCH"


def test_common_layout_requires_explicit_confirmation(client):
    response = create(client)
    exam_id = response.json()["id"]
    response = client.put(
        f"/api/exams/{exam_id}/settings",
        headers=headers(etag=response.headers["etag"]),
        json={"pages_per_student": 2, "scan_order_confirmed": True},
    )
    for kind in ("scans", "roster", "rubric"):
        response = upload(client, exam_id, response.headers["etag"], kind)
    result = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "LAYOUT_CONFIRMATION_REQUIRED"
