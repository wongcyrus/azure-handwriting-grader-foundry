# Azure handwriting grader: Foundry teacher application

Teacher-facing application for
[azure-handwriting-grader-skills](https://github.com/wongcyrus/azure-handwriting-grader-skills).
The reusable grading engine is a pinned optional dependency, not copied into this repository.

**Plan:** [Full implementation plan](docs/implementation-plan.md).
**Test/agent handoff:** [Persistent checklist](docs/test-checklist.md) and
[continuation instructions](AGENTS.md).

**Publication status:** The initial public commit contains this README and the plan
only. The tested implementation is local and awaiting review; setup commands below
apply after those implementation files are published.

## Implementation status

The current increment implements durable **local input review and offline engine preflight**:

- Bearer authentication: Entra delegated tokens or explicit synthetic development mode.
- Owner/tenant checks and a Teacher role; worker/admin identities cannot impersonate review.
- Exam settings and bounded input uploads, with server-computed hashes.
- ETag-based review transitions and explicit teacher attestation bound to the current snapshot.
- Prior artifacts/approval history retained when inputs change; current approval invalidated.
- A SQLite reference store that survives application restarts.
- Pinned-engine PDF/roster/rubric validation before review and again before approval.
- Workbook expansion limits, snapshot integrity and engine-provenance checks.

**Not implemented:** production Blob/Queue adapters, page rendering/orientation review,
attendance/box/score editors, pricing and budget gates, grading jobs,
Foundry skill hosting, Terraform deployment or reports. Input-review attestation
does **not** authorize grading. This increment contains no inference client or grading
endpoint and cannot make paid model calls.

SQLite is a local reference backend, not the proposed production architecture.
Development mode is for synthetic data only. The CLI binds to localhost in both modes.
Do not expose this starter server publicly or upload real student records.

## Local setup and tests

```sh
uv sync --extra dev --extra engine
uv run --frozen --extra dev --extra engine pytest
uv run --frozen --extra dev --extra engine ruff check .
uv run --frozen --extra dev --extra engine ruff format --check .
uv run --frozen --extra dev --extra engine python tools/smoke_review.py
```

Run with an ephemeral development token that is never printed:

```sh
export FOUNDRY_DEV_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run --frozen --extra engine handwriting-foundry --development
```

The API is at `http://127.0.0.1:8000`, with interactive documentation at `/docs`.
Requests need `Authorization: Bearer` using the local environment token.
Do not paste that token into chat, source files or shared logs.

Without `--development`, configure `FOUNDRY_ENTRA_TENANT_ID`,
`FOUNDRY_ENTRA_AUDIENCE` and optionally `FOUNDRY_ENTRA_SCOPE` (default `Exam.Access`).
The token must be an RS256 Entra v2 access token for that tenant/audience with the
delegated scope and `Teacher` app role. App-only identities are rejected.
Actual tenant registration, deployment and live Entra testing remain pending.

## Initial API

| Action | Route |
|---|---|
| Create exam | `POST /api/exams` |
| Read exam | `GET /api/exams/{id}` |
| Update layout settings | `PUT /api/exams/{id}/settings` |
| Upload scans, roster or rubric | `POST /api/exams/{id}/artifacts/{kind}` |
| Download an owned artifact | `GET /api/exams/{id}/artifacts/{artifact}` |
| Request input review | `POST /api/exams/{id}/review` |
| Attest reviewed snapshot | `POST /api/exams/{id}/approvals` |

Mutations of an existing exam require its returned `If-Match` ETag, including quotes.
Uploads use `application/octet-stream` and are limited to 10 MiB in this local increment.
Input review requires a PDF scan, an XLSX roster with the selected sheet and
`ID`, `NAME`, `CLASS` columns, and an XLSX rubric with the standard `Marking Scheme`
sheet. DOCX extraction and attendance CSV are not yet exposed by this API.
Both `scan_order_confirmed` and `same_layout_for_all` must be explicitly true;
`roster_sheet` defaults to `Roster`. All roster students are expected: absences
are not inferred. The PDF count must equal students times pages per student.

The engine validates roster and rubric semantics. Local caps are 200 PDF pages,
1,000 workbook archive entries and 16 MiB expanded data per workbook. These
limits do not replace future parser isolation/timeouts or page orientation review.
Files that fail validation remain uploaded but cannot enter review.

Approval requires `confirmed: true` and the returned `snapshot_sha256`.
The backend derives teacher identity from authentication; callers cannot supply it.
Concurrent or changed inputs produce a conflict instead of silently approving stale data.
Preflight is repeated before approval, and changing inputs/settings clears current
preflight and approval. Legacy review records without preflight cannot be approved;
update settings and request a fresh review rather than manufacturing validation.

## Engine dependency

The optional `engine` extra pins the source to commit
`3b155f9232cb0730587d89677c932ea049dd7f71`. CRUD/storage can run without the engine,
but review fails closed if the extra or its exact Git provenance is unavailable.
Never replace this pin with floating `main`. Cloud dependencies stay in this application,
not in the reusable grader's default installation.

No Azure resources, paid inference or production configuration are created by local setup.
