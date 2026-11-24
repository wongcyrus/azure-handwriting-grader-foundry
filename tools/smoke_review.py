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

from openpyxl import Workbook
from pypdf import PdfWriter


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
    args = parser.parse_args()
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    token = secrets.token_urlsafe(32)
    environment = {**os.environ, "FOUNDRY_DEV_TOKEN": token}
    with tempfile.TemporaryDirectory(prefix="foundry-http-smoke-") as directory:
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "handwriting_grader_cloud",
                    "--development",
                    "--database",
                    str(Path(directory) / "control.sqlite3"),
                    "--port",
                    str(port),
                ],
                env=environment,
                stdout=log,
                stderr=log,
            )
            base = f"http://127.0.0.1:{port}"

            def call(path, method="GET", body=None, etag=None, authenticated=True, binary=False):
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
                    return json.loads(response.read()), response.headers.get("ETag")

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
                exam, _ = call(
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
                mode = "explicit attendance" if args.attendance else "all-roster default"
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
