# Azure handwriting grader: Foundry teacher application

Teacher-facing application for
[azure-handwriting-grader-skills](https://github.com/wongcyrus/azure-handwriting-grader-skills).
The reusable grading engine is a pinned optional dependency, not copied into this repository.

**Plan:** [Full implementation plan](docs/implementation-plan.md).
**Test/agent handoff:** [Persistent checklist](docs/test-checklist.md) and
[continuation instructions](AGENTS.md).

**Publication status:** Public `main` currently contains the initial documentation
only. Foundation `e8ad9cf`, attendance `708cff1` and region review `9d05ab0` are local,
not pushed. The verified teacher canvas is local in this increment. Setup commands
below apply to this worktree or after implementation files are published.

## Implementation status

The current increment implements durable **local input/region review and offline engine preflight**:

- Bearer authentication: Entra delegated tokens or explicit synthetic development mode.
- Owner/tenant checks and a Teacher role; worker/admin identities cannot impersonate review.
- Exam settings and bounded input uploads, with server-computed hashes.
- ETag-based review transitions and explicit teacher attestation bound to the current snapshot.
- Prior artifacts/approval history retained when inputs change; current approval invalidated.
- A SQLite reference store that survives application restarts.
- Pinned-engine PDF/roster/rubric validation before review and again before approval.
- Workbook expansion limits, snapshot integrity and engine-provenance checks.
- Optional explicit attendance CSV, full roster/status preview and separate teacher attestation.
- Pinned-engine first-script JPEG previews and validated manual region drafts.
- Separate region attestation with preserved approved geometry, hashes and page-review coverage.
- React/TypeScript local canvas: pointer/keyboard editing, zoom, explicit page review,
  snapshot approval and conflict recovery without losing unsaved boxes.

**Not implemented:** production Blob/Queue adapters, all-script orientation/sequence review,
production sign-in, exam setup/attendance/score screens, pricing and budget gates, grading jobs,
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
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --attendance
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --regions
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --attendance --regions
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
| Upload scans, roster, rubric or attendance | `POST /api/exams/{id}/artifacts/{kind}` |
| Download an owned artifact | `GET /api/exams/{id}/artifacts/{artifact}` |
| Request input review | `POST /api/exams/{id}/review` |
| Attest reviewed snapshot | `POST /api/exams/{id}/approvals` |
| Prepare first-script template | `POST /api/exams/{id}/regions/prepare` |
| Read owned template JPEG | `GET /api/exams/{id}/regions/pages/{index}` |
| Save region draft | `PUT /api/exams/{id}/regions` |
| Attest reviewed geometry | `POST /api/exams/{id}/regions/approvals` |

Mutations of an existing exam require its returned `If-Match` ETag, including quotes.
Uploads use `application/octet-stream` and are limited to 10 MiB in this local increment.
Input review requires a PDF scan, an XLSX roster with the selected sheet and
`ID`, `NAME`, `CLASS` columns, and an XLSX rubric with the standard `Marking Scheme`
sheet. DOCX extraction is not yet exposed by this API.
Both `scan_order_confirmed` and `same_layout_for_all` must be explicitly true;
`roster_sheet` defaults to `Roster`. Without attendance CSV all roster students
are expected. An optional UTF-8 CSV requires exactly `ID,STATUS` headers and one
row per roster ID, with `present` or `absent`. The engine rejects missing,
duplicate/unknown IDs and a list with no present student. Absence is never inferred
from missing scans. PDF count must equal present students times pages per student.

The engine validates roster and rubric semantics. Local caps are 200 PDF pages,
1,000 workbook archive entries and 16 MiB expanded data per workbook. These
limits do not replace future parser isolation/timeouts or page orientation review.
Files that fail validation remain uploaded but cannot enter review.

Approval requires `confirmed: true` and the returned `snapshot_sha256`.
When CSV is supplied, `attendance_confirmed: true` is also required after inspecting
`preflight.attendance_review`. The server atomically records a distinct attendance
attestation bound to the CSV, roster and input snapshot. Absent students remain
in the preview with status `absent`, never a zero mark.
The backend derives teacher identity from authentication; callers cannot supply it.
Concurrent or changed inputs produce a conflict instead of silently approving stale data.
Preflight is repeated before approval, and changing inputs/settings clears current
preflight and both current approvals, retaining history. Legacy review records without preflight cannot be approved;
update settings and request a fresh review rather than manufacturing validation.

## Manual region review API

After `INPUTS_REVIEWED`, prepare the first present student's script using the
pinned engine's renderer. The returned `regions.pages` contains zero-based page
indexes, immutable JPEG hashes and actual rendered dimensions. These previews
are a common-layout template, **not** orientation/identity verification of all scans.
Embedded PDF rotation is reflected in rendered dimensions.

Save a draft with the current input `snapshot_sha256`, `annotations` keyed by
page index strings (`"0"`, `"1"`, etc.), and explicit `reviewed_pages` indexes.
Each box contains integer `x`, `y`, `width`, `height`, and a `label`. Coordinates
are **200-DPI rendered pixels from the top-left**, not PDF points, browser CSS
pixels or normalized fractions. The browser canvas and zoom/DPR conversion are
not implemented yet.

The pinned engine validates bounds, metadata labels and complete layouts. Draft
question labels must match the reviewed rubric; canonical aliases such as `Q1`
are supported. Approval requires NAME, ID and CLASS, ID on page zero, unique
canonical labels, every rubric question and every template page explicitly
reviewed. Submit the current input `snapshot_sha256`, the returned
`regions.review_sha256` as `regions_sha256`, and `confirmed: true`.
Success enters `REGIONS_REVIEWED`; it does **not** authorize grading.

Draft changes invalidate region approval only and preserve approved geometry in
attestation history. Any input/settings change invalidates previews and current
input/attendance/region approvals. Stale ETags/hashes, corrupt bytes or a changed
engine pin fail closed. JPEGs and the manifest commit atomically.

Local rendering is serialized per process. Admission caps are 4 million pixels
per page and 24 million per template, with a 10 MiB encoded-image cap. The fixed
200-DPI renderer requires `pypdfium2`; no unchecked fallback is used. These
controls do not replace production native-parser isolation/timeouts.

## Engine dependency

The optional `engine` extra pins the source to commit
`3b155f9232cb0730587d89677c932ea049dd7f71`. CRUD/storage can run without the engine,
but review fails closed if the extra or its exact Git provenance is unavailable.
Never replace this pin with floating `main`. Cloud dependencies stay in this application,
not in the reusable grader's default installation.

No Azure resources, paid inference or production configuration are created by local setup.

## Local teacher canvas

With the synthetic API running, create an explicitly fake exam:

```sh
uv run --frozen --extra dev --extra engine python tools/seed_canvas.py
cd apps/web
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Use the emitted exam ID and the matching synthetic
development token in the password field. The seed creates synthetic input
attestations for a demo, not evidence that a real teacher examined real scans.
Never use real student data or real identity tokens. Tokens remain in browser
memory only; refreshing signs out. Production Entra login is not implemented.

Prepare the template, draw boxes or add/edit them with the keyboard, review each
page, save, then explicitly confirm and approve. Editing clears that page's review.
Zoom/DPR are converted using actual CSS bounds into canonical image pixels.
A stale save preserves local edits; choose server reload or explicitly reapply
boxes to the latest compatible snapshot and review again. Changed input hashes
prohibit reapplying old coordinates.

From `apps/web`:

```sh
npm run build
npm run check
npm test
npm run test:browser
```

Browser tests require Google Chrome on this host. They start isolated localhost
API/Vite services on ports 18765/18766, use synthetic data, test DPR 1/2 and stop
the services afterward. Evidence and the synthetic test database are retained
under ignored `.local/test-results/`. Other browsers/production hosting remain
unverified.
