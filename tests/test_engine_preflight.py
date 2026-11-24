import json
import socket
import zipfile
from io import BytesIO
from types import SimpleNamespace

import pytest
from conftest import create, headers, upload

from handwriting_grader_cloud.preflight import EngineInputValidator

pytest.importorskip("handwriting_grader")
pytestmark = pytest.mark.engine


def synthetic_files(
    pages=4,
    roster_ids=("001", "002"),
    roster_sheet="Roster",
    roster_header=("ID", "NAME", "CLASS"),
    marks=5,
):
    from openpyxl import Workbook
    from pypdf import PdfWriter

    pdf = BytesIO()
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    writer.close()
    roster = Workbook()
    roster.active.title = roster_sheet
    roster.active.append(roster_header)
    for identifier in roster_ids:
        roster.active.append([identifier, "Synthetic Student", "Synthetic Class"])
    roster_bytes = BytesIO()
    roster.save(roster_bytes)
    roster.close()
    rubric = Workbook()
    rubric.active.title = "Marking Scheme"
    rubric.active.append(["question_number", "question_text", "marking_scheme", "marks"])
    rubric.active.append(["1", "Synthetic question", "Synthetic criterion", marks])
    rubric_bytes = BytesIO()
    rubric.save(rubric_bytes)
    rubric.close()
    return {
        "scans": pdf.getvalue(),
        "roster": roster_bytes.getvalue(),
        "rubric": rubric_bytes.getvalue(),
    }


@pytest.fixture(autouse=True)
def real_engine_without_network(service, monkeypatch):
    from handwriting_grader.azure_ai import AzureClient

    def forbidden(*_args, **_kwargs):
        pytest.fail(
            "Offline engine preflight must not construct Azure clients or access the network."
        )

    monkeypatch.setattr(AzureClient, "__init__", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    service.validator = EngineInputValidator()


def send_for_review(client, files):
    response = create(client)
    exam_id = response.json()["id"]
    for kind, content in files.items():
        response = upload(client, exam_id, response.headers["etag"], kind, content)
    result = client.post(
        f"/api/exams/{exam_id}/review", headers=headers(etag=response.headers["etag"])
    )
    return exam_id, response, result


def test_real_files_are_validated_and_approval_keeps_provenance(client):
    exam_id, _, response = send_for_review(client, synthetic_files())
    assert response.status_code == 200, response.text
    preflight = response.json()["preflight"]
    assert preflight["summary"]["students"] == 2
    assert preflight["summary"]["pdf_pages"] == 4
    assert preflight["summary"]["questions"] == 1
    assert preflight["summary"]["total_marks"] == 5
    response = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    assert response.status_code == 200
    assert response.json()["approvals"][0]["preflight_engine_commit"] == preflight["engine_commit"]


@pytest.mark.parametrize("pages", [0, 3, 5])
def test_empty_or_mismatched_pdf_does_not_enter_review(client, pages):
    exam_id, before, result = send_for_review(client, synthetic_files(pages=pages))
    assert result.status_code == 400
    assert result.json()["error"]["code"] == "INVALID_INPUTS"
    current = client.get(f"/api/exams/{exam_id}", headers=headers())
    assert current.headers["etag"] == before.headers["etag"]
    assert current.json()["preflight"] is None


def test_corrupt_pdf_is_rejected(client):
    files = synthetic_files()
    files["scans"] = b"not a PDF"
    _, _, response = send_for_review(client, files)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUTS"


@pytest.mark.parametrize(
    "changes",
    [
        {"roster_ids": ("001", "001")},
        {"roster_ids": ()},
        {"roster_sheet": "Different"},
        {"roster_header": ("ID", "NAME", "OTHER")},
    ],
)
def test_roster_errors_are_rejected_by_existing_engine(client, changes):
    _, _, response = send_for_review(client, synthetic_files(**changes))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_INPUTS"


@pytest.mark.parametrize("marks", [0, -1, "=2+3"])
def test_invalid_or_formula_rubric_marks_are_rejected(client, marks):
    _, _, response = send_for_review(client, synthetic_files(marks=marks))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_RUBRIC"


def test_non_workbook_and_expansion_limit_are_rejected(client, monkeypatch):
    import handwriting_grader_cloud.preflight as preflight

    files = synthetic_files()
    files["roster"] = b"ID,NAME,CLASS\n001,Synthetic,Class"
    _, _, response = send_for_review(client, files)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_WORKBOOK"
    monkeypatch.setattr(preflight, "MAX_EXPANDED_WORKBOOK_BYTES", 10)
    _, _, response = send_for_review(client, synthetic_files())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_WORKBOOK"


def test_pdf_page_limit_is_enforced(client, monkeypatch):
    import handwriting_grader_cloud.preflight as preflight

    monkeypatch.setattr(preflight, "MAX_PDF_PAGES", 3)
    _, _, response = send_for_review(client, synthetic_files())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INPUT_LIMIT"


def test_engine_pin_change_after_review_blocks_approval(client, monkeypatch):
    import handwriting_grader_cloud.preflight as preflight

    exam_id, _, response = send_for_review(client, synthetic_files())
    assert response.status_code == 200
    monkeypatch.setattr(
        preflight,
        "distribution",
        lambda _name: SimpleNamespace(
            read_text=lambda _file: json.dumps({"vcs_info": {"commit_id": "changed"}})
        ),
    )
    result = client.post(
        f"/api/exams/{exam_id}/approvals",
        headers=headers(etag=response.headers["etag"]),
        json={"snapshot_sha256": response.json()["snapshot_sha256"], "confirmed": True},
    )
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "ENGINE_PIN_MISMATCH"
    assert client.get(f"/api/exams/{exam_id}", headers=headers()).json()["approvals"] == []


@pytest.mark.parametrize("case", ["macro", "compression", "broken_xml", "entries", "total_marks"])
def test_workbook_policy_and_parser_errors_fail_closed(client, monkeypatch, case):
    import handwriting_grader_cloud.preflight as preflight

    files = synthetic_files()
    if case == "entries":
        monkeypatch.setattr(preflight, "MAX_WORKBOOK_ENTRIES", 1)
    elif case == "total_marks":
        from openpyxl import load_workbook

        workbook = load_workbook(BytesIO(files["rubric"]))
        workbook["Marking Scheme"]["D2"] = 1e308
        workbook["Marking Scheme"].append(["2", "Synthetic", "Synthetic", 1e308])
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        files["rubric"] = output.getvalue()
    else:
        output = BytesIO()
        compression = zipfile.ZIP_BZIP2 if case == "compression" else zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(BytesIO(files["rubric"])) as source:
            with zipfile.ZipFile(output, "w", compression=compression) as target:
                for entry in source.infolist():
                    content = source.read(entry)
                    if case == "broken_xml" and entry.filename == "xl/workbook.xml":
                        content = b"<invalid"
                    target.writestr(entry.filename, content)
                if case == "macro":
                    target.writestr("xl/vbaProject.bin", b"synthetic macro placeholder")
        files["rubric"] = output.getvalue()
    exam_id, _, response = send_for_review(client, files)
    assert response.status_code == 400
    expected = "INVALID_RUBRIC" if case in {"broken_xml", "total_marks"} else "INVALID_WORKBOOK"
    assert response.json()["error"]["code"] == expected
    assert client.get(f"/api/exams/{exam_id}", headers=headers()).json()["state"] == "SETUP"
