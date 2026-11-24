import re
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import Authenticator, Principal
from .errors import ApplicationError
from .models import (
    ArtifactKind,
    CreateExam,
    ExamSettings,
    RegionApproval,
    RegionDraft,
    ReviewApproval,
)
from .service import ExamService

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(service: ExamService, authenticator: Authenticator) -> FastAPI:
    app = FastAPI(title="Handwriting Foundry: initial review API", version="0.1.0")
    bearer = HTTPBearer(auto_error=False)

    def principal(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> Principal:
        return authenticator.authenticate(credentials.credentials if credentials else None)

    def expected_version(if_match: Annotated[str | None, Header()] = None) -> int:
        if if_match is None:
            raise ApplicationError("VERSION_REQUIRED", "An If-Match ETag is required.", 428)
        if not re.fullmatch(r'"[1-9][0-9]{0,17}"', if_match):
            raise ApplicationError("INVALID_VERSION", 'Use the ETag returned by the API, e.g. "1".')
        return int(if_match[1:-1])

    teacher = Annotated[Principal, Depends(principal)]
    version = Annotated[int, Depends(expected_version)]

    @app.exception_handler(ApplicationError)
    async def application_error(_request: Request, error: ApplicationError):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
        content = {"code": error.code, "message": error.message}
        if error.details is not None:
            content["details"] = error.details
        return JSONResponse(
            status_code=error.status,
            content={"error": content},
            headers=headers,
        )

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def result(document: dict) -> JSONResponse:
        return JSONResponse(document, headers={"ETag": f'"{document["version"]}"'})

    @app.get("/health")
    def health():
        return {"status": "ok", "stage": "initial-input-review", "inference_enabled": False}

    @app.post("/api/exams", status_code=201)
    def create_exam(request: CreateExam, caller: teacher):
        response = result(service.create(caller, request))
        response.status_code = 201
        return response

    @app.get("/api/exams")
    def list_exams(
        caller: teacher,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: UUID | None = None,
    ):
        return service.list_owned(caller, limit, str(cursor) if cursor else "")

    @app.get("/api/exams/{exam_id}")
    def get_exam(exam_id: UUID, caller: teacher):
        return result(service.owned(caller, str(exam_id)))

    @app.put("/api/exams/{exam_id}/settings")
    def update_settings(exam_id: UUID, settings: ExamSettings, caller: teacher, expected: version):
        return result(service.settings(caller, str(exam_id), expected, settings.model_dump()))

    @app.post("/api/exams/{exam_id}/artifacts/{kind}")
    async def upload(
        exam_id: UUID, kind: ArtifactKind, request: Request, caller: teacher, expected: version
    ):
        service.current(caller, str(exam_id), expected)
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            raise ApplicationError("INVALID_UPLOAD_TYPE", "Use application/octet-stream.", 415)
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
                raise ApplicationError("UPLOAD_TOO_LARGE", "The local upload limit is 10 MiB.", 413)
            content.extend(chunk)
        return result(service.attach(caller, str(exam_id), expected, kind, bytes(content)))

    @app.get("/api/exams/{exam_id}/artifacts/{artifact_id}")
    def download(exam_id: UUID, artifact_id: UUID, caller: teacher):
        content = service.content(caller, str(exam_id), str(artifact_id))
        return Response(
            content,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{artifact_id}.bin"',
                "Content-Security-Policy": "sandbox; default-src 'none'",
            },
        )

    @app.post("/api/exams/{exam_id}/review")
    def request_review(exam_id: UUID, caller: teacher, expected: version):
        return result(service.request_review(caller, str(exam_id), expected))

    @app.post("/api/exams/{exam_id}/approvals")
    def approve(exam_id: UUID, request: ReviewApproval, caller: teacher, expected: version):
        return result(service.approve(caller, str(exam_id), expected, request))

    @app.post("/api/exams/{exam_id}/regions/prepare")
    def prepare_regions(exam_id: UUID, caller: teacher, expected: version):
        return result(service.prepare_regions(caller, str(exam_id), expected))

    @app.get("/api/exams/{exam_id}/regions/pages/{page_index}")
    def region_page(exam_id: UUID, page_index: int, caller: teacher):
        return Response(
            service.region_page(caller, str(exam_id), page_index),
            media_type="image/jpeg",
            headers={"Content-Security-Policy": "sandbox; default-src 'none'"},
        )

    @app.put("/api/exams/{exam_id}/regions")
    def save_regions(exam_id: UUID, request: RegionDraft, caller: teacher, expected: version):
        return result(service.save_regions(caller, str(exam_id), expected, request))

    @app.post("/api/exams/{exam_id}/regions/approvals")
    def approve_regions(exam_id: UUID, request: RegionApproval, caller: teacher, expected: version):
        return result(service.approve_regions(caller, str(exam_id), expected, request))

    return app
