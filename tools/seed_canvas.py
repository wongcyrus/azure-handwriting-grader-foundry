"""Create an explicitly synthetic local exam for canvas development/browser tests."""

import argparse
import json
import os
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from smoke_review import synthetic_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--export-dir", type=Path, help="Export fake files offline to a new directory"
    )
    parser.add_argument(
        "--attendance", action="store_true", help="One synthetic present/absent pair"
    )
    args = parser.parse_args()
    if args.export_dir is not None:
        args.export_dir.mkdir(parents=True, exist_ok=False)
        paths = {}
        for kind, content in synthetic_files(args.attendance).items():
            suffix = ".pdf" if kind == "scans" else ".csv" if kind == "attendance" else ".xlsx"
            path = args.export_dir / (kind + suffix)
            path.write_bytes(content)
            paths[kind] = str(path.resolve())
        print(json.dumps(paths))
        return
    address = urlsplit(args.base_url)
    if (
        address.scheme != "http"
        or address.hostname not in {"127.0.0.1", "localhost"}
        or address.username is not None
        or address.password is not None
        or address.path not in {"", "/"}
        or address.query
        or address.fragment
    ):
        parser.error("Use a plain localhost HTTP API URL.")
    token = os.environ.get("FOUNDRY_DEV_TOKEN", "")
    if len(token) < 32 or "." in token:
        parser.error("Set a synthetic FOUNDRY_DEV_TOKEN; real identity tokens are prohibited.")
    base = args.base_url.rstrip("/")

    def call(path, method="GET", body=None, etag=None, binary=False):
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            headers["Content-Type"] = "application/octet-stream" if binary else "application/json"
        if etag:
            headers["If-Match"] = etag
        data = body if binary else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read()), response.headers.get("ETag")

    health, _ = call("/health")
    if health.get("inference_enabled") is not False:
        parser.error("This seed requires the local no-inference API.")
    exam, etag = call(
        "/api/exams",
        "POST",
        {
            "title": "Synthetic canvas demonstration",
            "settings": {
                "pages_per_student": 2,
                "scan_order_confirmed": True,
                "same_layout_for_all": True,
            },
        },
    )
    exam_id = exam["id"]
    for kind, content in synthetic_files(args.attendance).items():
        exam, etag = call(
            f"/api/exams/{exam_id}/artifacts/{kind}", "POST", content, etag, binary=True
        )
    exam, etag = call(f"/api/exams/{exam_id}/review", "POST", etag=etag)
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
    print(json.dumps({"exam_id": exam_id, "state": exam["state"]}))


if __name__ == "__main__":
    main()
