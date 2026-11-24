from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from handwriting_grader_cloud.api import create_app
from handwriting_grader_cloud.auth import Principal
from handwriting_grader_cloud.errors import ApplicationError
from handwriting_grader_cloud.repository import SQLiteRepository
from handwriting_grader_cloud.service import ExamService

TEACHER = Principal("school-a", "teacher-a", frozenset({"Teacher"}))
OTHER_TEACHER = Principal("school-a", "teacher-b", frozenset({"Teacher"}))
OTHER_TENANT = Principal("school-b", "teacher-a", frozenset({"Teacher"}))
WORKER = Principal("school-a", "worker", frozenset({"StageWorker"}))
ADMIN = Principal("school-a", "admin", frozenset({"Administrator"}))


class FakeAuthenticator:
    def authenticate(self, token):
        identities = {
            "teacher": TEACHER,
            "other": OTHER_TEACHER,
            "tenant": OTHER_TENANT,
            "worker": WORKER,
            "admin": ADMIN,
        }
        if token not in identities:
            raise ApplicationError("UNAUTHENTICATED", "Test authentication failed.", 401)
        return identities[token]


class FakeInputValidator:
    """Domain tests isolate state/auth; engine-marked tests use real validators."""

    def validate(self, document, contents):
        return {"engine_commit": "test-double", "policy_version": 1, "summary": {}}


@pytest.fixture
def service(tmp_path: Path):
    return ExamService(SQLiteRepository(tmp_path / "control.sqlite3"), FakeInputValidator())


@pytest.fixture
def client(service):
    with TestClient(create_app(service, FakeAuthenticator())) as value:
        yield value


def headers(token="teacher", etag=None):
    result = {"Authorization": f"Bearer {token}"}
    if etag is not None:
        result["If-Match"] = etag
    return result


def create(client, confirmed=True):
    response = client.post(
        "/api/exams",
        headers=headers(),
        json={
            "title": "Synthetic exam",
            "settings": {
                "pages_per_student": 2,
                "scan_order_confirmed": confirmed,
                "same_layout_for_all": True,
            },
        },
    )
    assert response.status_code == 201
    return response


def upload(client, exam_id, etag, kind, content=b"synthetic input fixture"):
    response = client.post(
        f"/api/exams/{exam_id}/artifacts/{kind}",
        headers={**headers(etag=etag), "Content-Type": "application/octet-stream"},
        content=content,
    )
    assert response.status_code == 200
    return response


def ready(client):
    response = create(client)
    exam_id = response.json()["id"]
    for kind in ("scans", "roster", "rubric"):
        response = upload(client, exam_id, response.headers["etag"], kind)
    response = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    assert response.status_code == 200
    return response
