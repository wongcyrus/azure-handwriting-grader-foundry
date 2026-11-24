from io import BytesIO
from types import SimpleNamespace

import pytest
from conftest import TEACHER, create, headers, upload
from test_engine_preflight import send_for_review, synthetic_files

pytestmark = pytest.mark.engine


def approved_inputs(client, files=None):
    exam_id, _, response = send_for_review(client, files or synthetic_files())
    response = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    assert response.status_code == 200, response.text
    return response


def prepare(client, response):
    return client.post(
        f"/api/exams/{response.json()['id']}/regions/prepare",
        headers=headers(etag=response.headers["etag"]),
    )


@pytest.fixture
def prepared(client):
    response = prepare(client, approved_inputs(client))
    assert response.status_code == 200, response.text
    return response


def draft_body(response):
    def box(label):
        return {"x": 0, "y": 0, "width": 20, "height": 20, "label": label}

    return {
        "snapshot_sha256": response.json()["snapshot_sha256"],
        "annotations": {"0": [box("ID"), box("NAME"), box("CLASS")], "1": [box("Q1")]},
        "reviewed_pages": [0, 1],
    }


def save_draft(client, response, body=None):
    return client.put(
        f"/api/exams/{response.json()['id']}/regions",
        headers=headers(etag=response.headers["etag"]),
        json=body or draft_body(response),
    )


def approve(client, response, **changes):
    return client.post(
        f"/api/exams/{response.json()['id']}/regions/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={
            "snapshot_sha256": response.json()["snapshot_sha256"],
            "regions_sha256": response.json()["regions"]["review_sha256"],
            "confirmed": True,
            **changes,
        },
    )


def test_rendered_template_and_geometry_approval_survive_restart(client, prepared, service):
    from PIL import Image

    from handwriting_grader_cloud.repository import SQLiteRepository

    document = prepared.json()
    regions = document["regions"]
    assert regions["snapshot_sha256"] == document["snapshot_sha256"]
    assert len(regions["pages"]) == document["settings"]["pages_per_student"]
    for page in regions["pages"]:
        image = client.get(
            f"/api/exams/{document['id']}/regions/pages/{page['index']}", headers=headers()
        )
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"
        assert image.headers["cache-control"] == "no-store"
        with Image.open(BytesIO(image.content)) as rendered:
            assert rendered.size == (page["width"], page["height"])
    saved = save_draft(client, prepared)
    assert saved.status_code == 200, saved.text
    approved = approve(client, saved)
    assert approved.status_code == 200, approved.text
    document = approved.json()
    assert document["state"] == "REGIONS_REVIEWED"
    approval = document["approvals"][-1]
    assert approval["kind"] == "regions_review_attestation"
    assert approval["actor_id"] == "teacher-a"
    assert approval["regions_sha256"] == document["regions"]["review_sha256"]
    assert approval["reviewed_regions"] == document["regions"]
    assert SQLiteRepository(service.repository.path).get(document["id"]) == document
    assert approve(client, saved).status_code == 409


def test_inputs_must_be_approved_before_rendering(client):
    response = create(client)
    assert prepare(client, response).status_code == 409
    _, _, response = send_for_review(client, synthetic_files())
    assert prepare(client, response).status_code == 409


@pytest.mark.parametrize(
    "kind,status",
    [
        ("missing_page", 400),
        ("padded_page", 400),
        ("extra_page", 400),
        ("unknown_question", 400),
        ("out_of_bounds", 400),
        ("lowercase_id", 400),
        ("path_label", 400),
        ("padded_label", 400),
        ("float_coordinate", 422),
        ("boolean_coordinate", 422),
        ("duplicate_review", 400),
        ("unknown_review", 400),
    ],
)
def test_invalid_drafts_do_not_change_review(client, prepared, kind, status):
    body = draft_body(prepared)
    if kind == "missing_page":
        body["annotations"].pop("1")
    elif kind == "padded_page":
        body["annotations"][" 0"] = body["annotations"].pop("0")
    elif kind == "extra_page":
        body["annotations"]["2"] = []
    elif kind == "unknown_question":
        body["annotations"]["1"][0]["label"] = "2"
    elif kind == "out_of_bounds":
        body["annotations"]["0"][0]["width"] = prepared.json()["regions"]["pages"][0]["width"] + 1
    elif kind in {"lowercase_id", "path_label", "padded_label"}:
        body["annotations"]["0"][0]["label"] = {
            "lowercase_id": "id",
            "path_label": "../ID",
            "padded_label": " ID ",
        }[kind]
    elif kind in {"float_coordinate", "boolean_coordinate"}:
        body["annotations"]["0"][0]["x"] = 1.5 if kind == "float_coordinate" else True
    elif kind == "duplicate_review":
        body["reviewed_pages"] = [0, 0]
    else:
        body["reviewed_pages"] = [0, 2]
    result = save_draft(client, prepared, body)
    assert result.status_code == status
    current = client.get(f"/api/exams/{prepared.json()['id']}", headers=headers())
    assert current.headers["etag"] == prepared.headers["etag"]
    assert current.json()["regions"] == prepared.json()["regions"]


@pytest.mark.parametrize(
    "kind", ["unreviewed_page", "missing_metadata", "id_on_second_page", "duplicate_alias"]
)
def test_incomplete_geometry_cannot_be_approved(client, prepared, kind):
    body = draft_body(prepared)
    if kind == "unreviewed_page":
        body["reviewed_pages"] = [0]
    elif kind == "missing_metadata":
        body["annotations"]["0"].pop()
    elif kind == "id_on_second_page":
        body["annotations"]["1"].append(body["annotations"]["0"].pop(0))
    else:
        duplicate = {**body["annotations"]["1"][0], "label": "1.0"}
        body["annotations"]["1"].append(duplicate)
    saved = save_draft(client, prepared, body)
    assert saved.status_code == 200
    assert approve(client, saved).status_code == 400
    current = client.get(f"/api/exams/{prepared.json()['id']}", headers=headers()).json()
    assert current["current_region_approval"] is None
    assert len(current["approvals"]) == 1


def test_every_rubric_question_requires_a_region(client):
    from openpyxl import load_workbook

    files = synthetic_files()
    workbook = load_workbook(BytesIO(files["rubric"]))
    workbook.active.append(["2", "Synthetic question", "Synthetic criterion", 5])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    files["rubric"] = output.getvalue()
    response = prepare(client, approved_inputs(client, files))
    saved = save_draft(client, response)
    assert saved.status_code == 200
    assert approve(client, saved).status_code == 400


@pytest.mark.parametrize(
    "changes,status",
    [
        ({"confirmed": False}, 400),
        ({"confirmed": "true"}, 422),
        ({"confirmed": 1}, 422),
        ({"regions_sha256": "0" * 64}, 409),
        ({"snapshot_sha256": "0" * 64}, 409),
    ],
)
def test_region_approval_requires_literal_confirmation_and_current_hashes(
    client, prepared, changes, status
):
    saved = save_draft(client, prepared)
    assert approve(client, saved, **changes).status_code == status


def test_edits_invalidate_geometry_only_and_keep_approved_revision(client, prepared):
    saved = save_draft(client, prepared)
    approved = approve(client, saved)
    before = approved.json()
    body = draft_body(approved)
    body["annotations"]["1"][0]["x"] = 10
    edited = save_draft(client, approved, body)
    assert edited.status_code == 200
    assert edited.json()["current_region_approval"] is None
    assert edited.json()["current_approval"] == before["current_approval"]
    assert edited.json()["approvals"][-1]["reviewed_regions"] == before["regions"]
    assert edited.json()["regions"]["review_sha256"] != before["regions"]["review_sha256"]
    assert save_draft(client, approved, body).status_code == 409


@pytest.mark.parametrize("kind", ["scans", "rubric", "roster", "attendance", "settings"])
def test_input_changes_invalidate_rendered_review(client, prepared, kind):
    approved = approve(client, save_draft(client, prepared))
    exam_id = approved.json()["id"]
    if kind == "settings":
        changed = client.put(
            f"/api/exams/{exam_id}/settings",
            headers=headers(etag=approved.headers["etag"]),
            json={**approved.json()["settings"], "pages_per_student": 1},
        )
    else:
        content = (
            b"ID,STATUS\n001,present\n002,absent\n"
            if kind == "attendance"
            else synthetic_files()[kind]
        )
        changed = upload(client, exam_id, approved.headers["etag"], kind, content)
    assert changed.json()["regions"] is None
    assert changed.json()["current_region_approval"] is None
    assert len(changed.json()["approvals"]) == 2
    assert client.get(f"/api/exams/{exam_id}/regions/pages/0", headers=headers()).status_code == 409


@pytest.mark.parametrize(
    "identity,status", [("other", 404), ("tenant", 404), ("worker", 403), ("", 401)]
)
def test_region_routes_are_owner_and_tenant_scoped(client, prepared, identity, status):
    exam_id = prepared.json()["id"]
    assert (
        client.get(f"/api/exams/{exam_id}/regions/pages/0", headers=headers(identity)).status_code
        == status
    )
    for method, path, body in [
        ("post", "regions/prepare", None),
        ("put", "regions", draft_body(prepared)),
        (
            "post",
            "regions/approvals",
            {
                "snapshot_sha256": prepared.json()["snapshot_sha256"],
                "regions_sha256": prepared.json()["regions"]["review_sha256"],
                "confirmed": True,
            },
        ),
    ]:
        result = getattr(client, method)(
            f"/api/exams/{exam_id}/{path}",
            headers=headers(identity, prepared.headers["etag"]),
            json=body,
        )
        assert result.status_code == status


@pytest.mark.parametrize("target", ["scans", "page"])
def test_corrupt_inputs_or_images_block_region_approval(client, prepared, service, target):
    saved = save_draft(client, prepared)
    document = saved.json()
    artifact_id = (
        document["artifacts"]["scans"]["id"]
        if target == "scans"
        else document["regions"]["pages"][0]["artifact_id"]
    )
    with service.repository.connection() as connection:
        connection.execute("UPDATE artifacts SET content=? WHERE id=?", (b"corrupt", artifact_id))
    assert approve(client, saved).status_code == 409
    current = client.get(f"/api/exams/{document['id']}", headers=headers()).json()
    assert current["current_region_approval"] is None


def test_large_page_is_rejected_before_engine_render(client, monkeypatch):
    import handwriting_grader.regions as engine
    from pypdf import PdfWriter

    files = synthetic_files()
    writer = PdfWriter()
    for _ in range(4):
        writer.add_blank_page(width=2000, height=2000)
    output = BytesIO()
    writer.write(output)
    writer.close()
    files["scans"] = output.getvalue()
    approved = approved_inputs(client, files)

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized PDFs must fail before rendering allocates pixels.")

    monkeypatch.setattr(engine, "prepare_regions", forbidden)
    result = prepare(client, approved)
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "RENDER_LIMIT"
    current = client.get(f"/api/exams/{approved.json()['id']}", headers=headers())
    assert current.headers["etag"] == approved.headers["etag"]
    assert current.json()["regions"] is None


def test_render_race_persists_neither_manifest_nor_images(client, service, monkeypatch):
    import handwriting_grader_cloud.service as module

    approved = approved_inputs(client)
    exam_id = approved.json()["id"]
    original = module.render_template

    def render_then_change(document, content):
        result = original(document, content)
        service.settings(TEACHER, exam_id, document["version"], document["settings"])
        return result

    monkeypatch.setattr(module, "render_template", render_then_change)
    assert prepare(client, approved).status_code == 409
    assert client.get(f"/api/exams/{exam_id}", headers=headers()).json()["regions"] is None
    with service.repository.connection() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE exam_id=?", (exam_id,)
            ).fetchone()[0]
            == 3
        )


def test_pdf_rotation_uses_rendered_dimensions_for_box_bounds(client):
    from pypdf import PdfWriter

    files = synthetic_files()
    writer = PdfWriter()
    for _ in range(4):
        writer.add_blank_page(width=100, height=200).rotate(90)
    output = BytesIO()
    writer.write(output)
    writer.close()
    files["scans"] = output.getvalue()
    response = prepare(client, approved_inputs(client, files))
    assert response.status_code == 200
    page = response.json()["regions"]["pages"][0]
    assert page["width"] > page["height"]
    body = draft_body(response)
    body["annotations"]["0"][0]["x"] = 300
    assert save_draft(client, response, body).status_code == 200


def test_template_pixel_limit_is_checked_before_rendering(client, monkeypatch):
    import handwriting_grader.regions as engine
    from pypdf import PdfWriter

    files = synthetic_files()
    writer = PdfWriter()
    for _ in range(40):
        writer.add_blank_page(width=600, height=600)
    output = BytesIO()
    writer.write(output)
    writer.close()
    files["scans"] = output.getvalue()
    response = create(client)
    exam_id = response.json()["id"]
    response = client.put(
        f"/api/exams/{exam_id}/settings",
        headers=headers(etag=response.headers["etag"]),
        json={**response.json()["settings"], "pages_per_student": 20},
    )
    for kind, content in files.items():
        response = upload(client, exam_id, response.headers["etag"], kind, content)
    response = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    response = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    assert response.status_code == 200

    def forbidden(*args, **kwargs):
        pytest.fail("Aggregate pixel limits must be enforced before rendering.")

    monkeypatch.setattr(engine, "prepare_regions", forbidden)
    result = prepare(client, response)
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "RENDER_LIMIT"


def test_region_mutations_require_etags_and_page_indexes_are_bounded(client, prepared):
    exam_id = prepared.json()["id"]
    assert (
        client.put(
            f"/api/exams/{exam_id}/regions", headers=headers(), json=draft_body(prepared)
        ).status_code
        == 428
    )
    assert (
        client.put(
            f"/api/exams/{exam_id}/regions", headers=headers(etag='"1"'), json=draft_body(prepared)
        ).status_code
        == 409
    )
    for index in (-1, 2):
        assert (
            client.get(f"/api/exams/{exam_id}/regions/pages/{index}", headers=headers()).status_code
            == 404
        )


def test_engine_change_after_rendering_blocks_region_approval(client, prepared, monkeypatch):
    import handwriting_grader_cloud.preflight as preflight

    saved = save_draft(client, prepared)
    monkeypatch.setattr(
        preflight,
        "distribution",
        lambda _name: SimpleNamespace(
            read_text=lambda _file: '{"vcs_info":{"commit_id":"changed"}}'
        ),
    )
    result = approve(client, saved)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "ENGINE_PIN_MISMATCH"
    assert (
        client.get(f"/api/exams/{prepared.json()['id']}", headers=headers()).json()[
            "current_region_approval"
        ]
        is None
    )
