"""Reproducible local HTTP check using generated synthetic files, never model calls."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from openpyxl import Workbook
from pypdf import PdfWriter

OPERATOR_SMOKE_SCRIPT = """
import os
import runpy
import socket
import time
from handwriting_grader.azure_ai import AzureClient
from handwriting_grader import attendance, grading, regions, rubric
from handwriting_grader_cloud.preflight import EngineInputValidator

def forbidden(*args, **kwargs):
    raise AssertionError("Offline smoke must not call AI, network, approval, grading or sleep")

AzureClient.__init__ = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
time.sleep = forbidden
for module, name in (
    (attendance, "approve_attendance"),
    (grading, "grade_exam"),
    (regions, "approve_regions"),
    (rubric, "approve_rubric"),
):
    setattr(module, name, forbidden)
if os.environ["FOUNDRY_SMOKE_REUSE_ONLY"] == "1":
    EngineInputValidator.validate = forbidden
runpy.run_module("handwriting_grader_cloud.operator", run_name="__main__")
"""


def run_operator(database, job_id, *, reuse_only=False, expected_returncode=0):
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            OPERATOR_SMOKE_SCRIPT,
            "--development",
            "--database",
            str(database),
            "--job-id",
            job_id,
        ],
        env={**os.environ, "FOUNDRY_SMOKE_REUSE_ONLY": "1" if reuse_only else "0"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == expected_returncode, "Unexpected offline operator outcome."
    return json.loads(completed.stdout)


def synthetic_files(attendance=False):
    pdf = BytesIO()
    writer = PdfWriter()
    for _ in range(2 if attendance else 4):
        writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    writer.close()
    roster = Workbook()
    roster.active.title = "Roster"
    roster.active.append(["ID", "NAME", "CLASS"])
    roster.active.append(["001", "Synthetic Student A", "Synthetic Class"])
    roster.active.append(["002", "Synthetic Student B", "Synthetic Class"])
    roster_bytes = BytesIO()
    roster.save(roster_bytes)
    roster.close()
    rubric = Workbook()
    rubric.active.title = "Marking Scheme"
    rubric.active.append(["question_number", "question_text", "marking_scheme", "marks"])
    rubric.active.append(["1", "Synthetic question", "Synthetic criterion", 5])
    rubric_bytes = BytesIO()
    rubric.save(rubric_bytes)
    rubric.close()
    files = {
        "scans": pdf.getvalue(),
        "roster": roster_bytes.getvalue(),
        "rubric": rubric_bytes.getvalue(),
    }
    if attendance:
        files["attendance"] = b"ID,STATUS\n001,present\n002,absent\n"
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--attendance", action="store_true", help="Exercise explicit present/absent review"
    )
    parser.add_argument(
        "--regions", action="store_true", help="Render and attest manual region review"
    )
    parser.add_argument(
        "--offline-jobs",
        action="store_true",
        help="Prepare, request, inspect and cancel an offline check",
    )
    parser.add_argument(
        "--offline-operator",
        action="store_true",
        help="Explicitly validate the named synthetic job and inspect current/historical results",
    )
    args = parser.parse_args()
    if args.offline_operator and not args.offline_jobs:
        parser.error("--offline-operator requires --offline-jobs and --regions.")
    if args.offline_jobs and not args.regions:
        parser.error("--offline-jobs requires --regions.")
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    token = secrets.token_urlsafe(32)
    environment = {**os.environ, "FOUNDRY_DEV_TOKEN": token}
    with tempfile.TemporaryDirectory(prefix="foundry-http-smoke-") as directory:
        database = Path(directory) / "control.sqlite3"
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "handwriting_grader_cloud",
                    "--development",
                    "--database",
                    str(database),
                    "--port",
                    str(port),
                ],
                env=environment,
                stdout=log,
                stderr=log,
            )
            base = f"http://127.0.0.1:{port}"

            def call(
                path,
                method="GET",
                body=None,
                etag=None,
                authenticated=True,
                binary=False,
                raw=False,
            ):
                headers = {
                    "Content-Type": "application/octet-stream" if binary else "application/json"
                }
                if authenticated:
                    headers["Authorization"] = f"Bearer {token}"
                if etag:
                    headers["If-Match"] = etag
                data = body if binary else (json.dumps(body).encode() if body is not None else None)
                request = urllib.request.Request(
                    base + path, data=data, headers=headers, method=method
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    content = response.read()
                    return (content if raw else json.loads(content)), response.headers.get("ETag")

            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("The local API exited before readiness.")
                    try:
                        health, _ = call("/health", authenticated=False)
                        assert health["inference_enabled"] is False
                        break
                    except (urllib.error.URLError, ConnectionError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("The local API did not become responsive.")
                try:
                    call("/api/exams", method="POST", body={}, authenticated=False)
                except urllib.error.HTTPError as error:
                    assert error.code == 401
                else:
                    raise AssertionError("Unauthenticated exam creation succeeded.")
                exam, etag = call(
                    "/api/exams",
                    "POST",
                    {
                        "title": "Synthetic live HTTP exam",
                        "settings": {
                            "pages_per_student": 2,
                            "scan_order_confirmed": True,
                            "same_layout_for_all": True,
                            "roster_sheet": "Roster",
                        },
                    },
                )
                exam_id = exam["id"]
                for kind, content in synthetic_files(args.attendance).items():
                    exam, etag = call(
                        f"/api/exams/{exam_id}/artifacts/{kind}",
                        "POST",
                        content,
                        etag,
                        binary=True,
                    )
                exam, etag = call(f"/api/exams/{exam_id}/review", "POST", etag=etag)
                assert exam["preflight"]["summary"]["students"] == (1 if args.attendance else 2)
                assert exam["preflight"]["summary"]["pdf_pages"] == (2 if args.attendance else 4)
                assert exam["preflight"]["summary"]["absent"] == (1 if args.attendance else 0)
                if args.attendance:
                    assert [
                        (row["id"], row["status"]) for row in exam["preflight"]["attendance_review"]
                    ] == [("001", "present"), ("002", "absent")]
                exam, etag = call(
                    f"/api/exams/{exam_id}/approvals",
                    "POST",
                    {
                        "snapshot_sha256": exam["snapshot_sha256"],
                        "confirmed": True,
                        "attendance_confirmed": args.attendance,
                    },
                    etag,
                )
                assert exam["state"] == "INPUTS_REVIEWED"
                assert len(exam["approvals"]) == (2 if args.attendance else 1)
                if args.attendance:
                    assert exam["approvals"][1]["kind"] == "attendance_review_attestation"
                    assert exam["current_attendance_approval"] == exam["approvals"][1]["id"]
                if args.regions:
                    from PIL import Image

                    exam, etag = call(f"/api/exams/{exam_id}/regions/prepare", "POST", etag=etag)
                    for page in exam["regions"]["pages"]:
                        image, _ = call(
                            f"/api/exams/{exam_id}/regions/pages/{page['index']}", raw=True
                        )
                        with Image.open(BytesIO(image)) as rendered:
                            assert rendered.size == (page["width"], page["height"])

                    def box(label):
                        return {"x": 0, "y": 0, "width": 20, "height": 20, "label": label}

                    exam, etag = call(
                        f"/api/exams/{exam_id}/regions",
                        "PUT",
                        {
                            "snapshot_sha256": exam["snapshot_sha256"],
                            "annotations": {
                                "0": [box("ID"), box("NAME"), box("CLASS")],
                                "1": [box("Q1")],
                            },
                            "reviewed_pages": [0, 1],
                        },
                        etag,
                    )
                    exam, etag = call(
                        f"/api/exams/{exam_id}/regions/approvals",
                        "POST",
                        {
                            "snapshot_sha256": exam["snapshot_sha256"],
                            "regions_sha256": exam["regions"]["review_sha256"],
                            "confirmed": True,
                        },
                        etag,
                    )
                    assert exam["state"] == "REGIONS_REVIEWED"
                    assert len(exam["approvals"]) == (3 if args.attendance else 2)
                    assert exam["approvals"][-1]["id"] == exam["current_region_approval"]
                if args.offline_jobs:
                    prepared, prepared_etag = call(
                        f"/api/exams/{exam_id}/offline-inputs",
                        "POST",
                        {"confirmed": True},
                        etag,
                    )
                    assert prepared_etag == etag
                    assert set(prepared) == {"checkpoint_id", "checkpoint_sha256", "exam_version"}
                    request = {
                        "checkpoint_id": prepared["checkpoint_id"],
                        "request_id": str(uuid4()),
                        "confirmed": True,
                    }
                    job, job_etag = call(f"/api/exams/{exam_id}/jobs", "POST", request, etag)
                    assert job_etag == etag
                    assert job["state"] == "PENDING_DISPATCH"
                    replay, _ = call(f"/api/exams/{exam_id}/jobs", "POST", request, etag)
                    assert replay == job
                    job_id = job["intent"]["id"]
                    page, _ = call(f"/api/exams/{exam_id}/jobs")
                    assert [item["job_id"] for item in page["items"]] == [job_id]
                    status, status_etag = call(f"/api/exams/{exam_id}/jobs/{job_id}")
                    assert status["state"] == "PENDING_DISPATCH"
                    assert status_etag == etag
                    assert not status["result_available"]
                    try:
                        call(f"/api/exams/{exam_id}/jobs/{job_id}/result")
                    except urllib.error.HTTPError as error:
                        assert error.code == 409
                        assert json.loads(error.read())["error"]["code"] == "RESULT_NOT_READY"
                    else:
                        raise AssertionError("A pending job returned a result.")
                    unchanged, _ = call(f"/api/exams/{exam_id}")
                    assert unchanged == exam
                    if args.offline_operator:
                        validated = run_operator(database, job_id)
                        assert validated["state"] == "VALIDATED"
                        assert validated["delivery_sends"] == validated["delivery_attempts"] == 1
                        assert validated["summary"] == {
                            key: exam["preflight"]["summary"][key]
                            for key in ("students", "absent", "pdf_pages", "total_marks")
                        }
                        status, status_etag = call(f"/api/exams/{exam_id}/jobs/{job_id}")
                        assert status["state"] == "VALIDATED"
                        assert status["result_available"]
                        assert status["result_sha256"] == validated["result_sha256"]
                        assert status_etag == etag
                        record, record_etag = call(f"/api/exams/{exam_id}/jobs/{job_id}/result")
                        assert record["job_id"] == job_id
                        assert record["binding"]["exam_version"] == exam["version"]
                        assert record_etag == etag
                        recovered = run_operator(database, job_id, reuse_only=True)
                        assert recovered["delivery_sends"] == 0
                        assert recovered["delivery_attempts"] == 1
                        assert recovered["result_sha256"] == validated["result_sha256"]
                        assert recovered["validated_at"] == validated["validated_at"]
                        after_recovery, _ = call(f"/api/exams/{exam_id}/jobs/{job_id}")
                        assert after_recovery == status
                        unchanged, _ = call(f"/api/exams/{exam_id}")
                        assert unchanged == exam
                    changed, current_etag = call(
                        f"/api/exams/{exam_id}/settings", "PUT", exam["settings"], etag
                    )
                    status, _ = call(f"/api/exams/{exam_id}/jobs/{job_id}")
                    assert status["state"] == (
                        "VALIDATED_HISTORICAL" if args.offline_operator else "STALE_INPUTS"
                    )
                    try:
                        call(
                            f"/api/exams/{exam_id}/jobs/{job_id}/cancel",
                            "POST",
                            {"confirmed": True},
                            etag,
                        )
                    except urllib.error.HTTPError as error:
                        assert error.code == 409
                    else:
                        raise AssertionError("A stale ETag cancelled the job.")
                    if args.offline_operator:
                        historical, historical_etag = call(
                            f"/api/exams/{exam_id}/jobs/{job_id}/result"
                        )
                        assert historical == record
                        assert historical_etag == current_etag
                        try:
                            call(
                                f"/api/exams/{exam_id}/jobs/{job_id}/cancel",
                                "POST",
                                {"confirmed": True},
                                current_etag,
                            )
                        except urllib.error.HTTPError as error:
                            assert error.code == 409
                            assert json.loads(error.read())["error"]["code"] == "JOB_COMPLETED"
                        else:
                            raise AssertionError("A completed result was cancelled.")
                        rejected = run_operator(
                            database, job_id, reuse_only=True, expected_returncode=1
                        )
                        assert rejected == {"error": {"code": "STALE_REVIEW"}}
                        final_status, _ = call(f"/api/exams/{exam_id}/jobs/{job_id}")
                        assert final_status == status
                        final_result, _ = call(f"/api/exams/{exam_id}/jobs/{job_id}/result")
                        assert final_result == record
                    else:
                        cancelled, _ = call(
                            f"/api/exams/{exam_id}/jobs/{job_id}/cancel",
                            "POST",
                            {"confirmed": True},
                            current_etag,
                        )
                        assert cancelled["state"] == "CANCELLED"
                        status, _ = call(f"/api/exams/{exam_id}/jobs/{job_id}")
                        assert status["state"] == "CANCELLED"
                    final, _ = call(f"/api/exams/{exam_id}")
                    assert final == changed
                mode = "explicit attendance" if args.attendance else "all-roster default"
                if args.regions:
                    mode += " and rendered region review"
                if args.offline_operator:
                    mode += " and explicit operator/current-historical results"
                elif args.offline_jobs:
                    mode += " and confirmed offline request/stale-safe cancellation"
                print(
                    f"PASS: live localhost auth, synthetic files, {mode}, pinned-engine "
                    "preflight and hash-bound teacher attestation(s); no inference."
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
