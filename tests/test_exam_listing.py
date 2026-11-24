import pytest
from conftest import OTHER_TEACHER, OTHER_TENANT, TEACHER, create, headers

from handwriting_grader_cloud.models import CreateExam, ExamSettings


def test_listing_returns_only_owned_summaries(client, service):
    own = create(client).json()
    request = CreateExam(title="Other synthetic exam", settings=ExamSettings(pages_per_student=2))
    for identity in (OTHER_TEACHER, OTHER_TENANT):
        service.create(identity, request)
    result = client.get("/api/exams", headers=headers())
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["exams"] == [
        {key: own[key] for key in ("id", "title", "state", "version")}
    ]
    assert result.json()["next_cursor"] is None


def test_cursor_pages_are_bounded_and_do_not_duplicate_exams(client):
    ids = sorted(create(client).json()["id"] for _ in range(7))
    found = []
    cursor = None
    while True:
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/api/exams", headers=headers(), params=params).json()
        assert len(page["exams"]) <= 2
        found.extend(row["id"] for row in page["exams"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert found == ids
    assert len(set(found)) == 7


def test_no_owned_exams_returns_an_empty_collection(client):
    assert client.get("/api/exams", headers=headers()).json() == {
        "exams": [],
        "next_cursor": None,
    }


@pytest.mark.parametrize("query", ["limit=0", "limit=51", "limit=-1", "cursor=not-a-uuid"])
def test_invalid_paging_parameters_are_rejected(client, query):
    assert client.get(f"/api/exams?{query}", headers=headers()).status_code == 422


@pytest.mark.parametrize("identity,status", [("worker", 403), ("admin", 403), ("", 401)])
def test_listing_requires_authenticated_teacher(client, identity, status):
    assert client.get("/api/exams", headers=headers(identity)).status_code == status


def test_query_parameters_cannot_override_authenticated_identity(client, service):
    own = create(client).json()
    foreign = service.create(
        OTHER_TEACHER, CreateExam(title="Foreign", settings=ExamSettings(pages_per_student=2))
    )
    result = client.get(
        "/api/exams?owner_id=teacher-b&tenant_id=school-b", headers=headers()
    ).json()
    assert [row["id"] for row in result["exams"]] == [own["id"]]
    cursor_page = service.list_owned(TEACHER, 20, foreign["id"])
    assert all(row["id"] == own["id"] for row in cursor_page["exams"])
