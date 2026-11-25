# Azure handwriting grader: Foundry teacher application

Teacher-facing application for
[azure-handwriting-grader-skills](https://github.com/wongcyrus/azure-handwriting-grader-skills).
The reusable grading engine is a pinned optional dependency, not copied into this repository.

**Plan:** [Full implementation plan](docs/implementation-plan.md).
**Test/agent handoff:** [Persistent checklist](docs/test-checklist.md) and
[continuation instructions](AGENTS.md).

**Publication status:** Public `main` contains the application through `9316676`,
including input/region review, teacher UI, workspace mapping and offline job
intents/outbox. Hosted offline CI passed for that commit. Fenced offline
execution/cancellation is committed locally as `8152657`, not pushed.
Outbox reconciliation is committed locally as `9631574`, also not pushed.
Bounded simulated delivery is committed locally as `cd6795f`, also not pushed.
One-shot offline consumption/lifecycle is committed locally as `48f3336`, not pushed.
The new teacher-owned offline job HTTP increment remains uncommitted pending review.

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
- Tenant/owner-scoped exam summaries with bounded cursor pagination and browser selection.
- Browser exam creation, PDF/XLSX/CSV uploads, explicit layout settings and full
  roster/rubric/attendance preview before independent human approvals.
- Internal offline approved-review workspace hydration and durable checkpoints:
  original input/image references, fixed relative paths and byte-identical recovery.
- Explicit API-owned projection of current review attestations into engine
  input approval files, checked by the pinned engine without granting a grading job.
- Internal explicit offline-validation job intents and atomic outbox records:
  stable request/message IDs, owner scoping and assignment-bound worker artifact reads.
- Internal read-only validation execution: five-minute fenced claims, stale-safe
  teacher cancellation, immutable results and safe recovery/reuse.
- Internal tenant-scoped outbox status and bounded cursor reconciliation:
  immutable stale/invalid-record holds without changing intents or teacher approvals.
- Bounded simulated delivery: durable send watermarks, three attempts with 5/30-second
  retry waits, lost-acknowledgement recovery and terminal operator-review holds.
- One-shot offline consumption and owner-only lifecycle/result inspection:
  confirmed scoped delivery, strict envelopes, fenced result reuse and explicit historical states.
- Confirmed teacher-owned offline preparation/request/cancellation HTTP routes,
  bounded job discovery and read-only lifecycle/historical result access.

**Not implemented:** production Blob/Queue adapters, all-script orientation/sequence review,
production sign-in, direct roster/rubric/score editors, pricing and budget gates, grading jobs,
Foundry skill hosting, Terraform deployment or reports. Input-review attestation
does **not** authorize grading. This increment contains no inference client or grading
endpoint and cannot make paid model calls.

SQLite is a local reference backend, not the proposed production architecture.
Development mode is for synthetic data only. The CLI binds to localhost in both modes.
Do not expose this starter server publicly or upload real student records.

### Offline review workspace bridge

`WorkspaceBridge` is server-side API/control code, not a worker permission.
Its confirmed owner-only preparation is exposed below; hydration/recovery remain
internal. It requires the authenticated owner's Teacher principal, current
exam version and current input/region attestations, with a separate attendance
attestation for explicit CSV. It reruns pinned-engine validation and rejects
stale approvals, changed files or incompatible checkpoint provenance.

```python
from pathlib import Path

from handwriting_grader_cloud.workspace import WorkspaceBridge

# service and principal come from the authenticated API/control context.
bridge = WorkspaceBridge(service, Path(".local/workspaces"))
workspace = bridge.hydrate(principal, exam_id, current_version)
recovered = bridge.restore(principal, exam_id, current_version, workspace.checkpoint_id)
```

The root is server-controlled and must be private/non-symlink. Each workspace
has an opaque generated directory; student names and checkpoint paths are not
accepted as filesystem destinations. SQLite atomically saves the checkpoint
and derived files after checking the exam version and all referenced bytes.
Recovery reconstructs the same relative paths and file bytes in a new root.

Default hydration is **not a grading-ready workspace**: it preserves API attestations in
`review-context.json` but generates no engine `approval.json`, model config,
grading manifest or job authority.

Authenticated control code can explicitly prepare compatible engine inputs:

```python
engine_inputs = bridge.prepare_engine_inputs(principal, exam_id, current_version)
```

This preserves the imported rubric XLSX bytes, saved region revision and
original API approval times. Explicit CSV uses the attendance attestation's
UUID as a stable review version and preserves all reviewed IDs/statuses.
No new human approval is recorded or inferred; the engine's `approve_*` actions
are never invoked. The engine's read-only `approved_inputs` validator checks
compatibility before publication and after recovery.

`engine-input-context.json` binds each projected approval to its API identity,
tenant, original time and file hash. The strict engine attendance format has
no actor/time fields, so this companion context retains that provenance.
The existing web preview replaces the need for another attendance-review XLSX;
the engine reads the matching JSON review. Without CSV the existing all-roster
default is preserved; absence is never inferred.

Passing engine input validation **does not authorize grading or paid work**.
Local projections are not authoritative cloud approvals and cannot grant jobs.
There is no model configuration, grading endpoint, unrestricted agent approval
tool or unrestricted worker permission here. Internal read-only job scope is
described below; paid budgets, incremental grading checkpoints and cloud storage
remain pending.

### Offline validation job control

Authenticated control code can explicitly request the fixed, non-paid
`validate_engine_inputs` stage from a current mapped checkpoint:

```python
from uuid import uuid4

from handwriting_grader_cloud.jobs import OfflineJobControl
from handwriting_grader_cloud.models import OfflineValidationRequest

control = OfflineJobControl(bridge)
request = OfflineValidationRequest(
    checkpoint_id=engine_inputs.checkpoint_id,
    request_id=uuid4(),
    confirmed=True,
)
job = control.request_validation(principal, exam_id, current_version, request)
```

Use the same request ID for retrying the same explicit teacher action. An
identical replay returns the same intent/message; conflicting checkpoint or
snapshot reuse is rejected. Admission writes the immutable job intent and
pending outbox together under the exam-version transaction, without changing
human approvals or the exam version.

`JobDispatcher` and `StageWorker` principals must come from a trusted identity
boundary, never request-body roles or teacher impersonation. A dispatcher sees
only its tenant's bounded outbox IDs and can record a same-tenant worker
assignment. Duplicate acknowledgement preserves the assignment/time; changing
the recipient is rejected. Assigned workers can read only the matching
job/message context and referenced, hash-checked artifacts while the approved
snapshot remains current.

Admission creates **local control records, not execution**; teacher admission
is also exposed through the confirmed HTTP route below. Dispatch remains internal.
`DISPATCHED` means an acknowledgement was recorded; no queue message is sent and
no validation or grading starts automatically. Read grants are not execution
claims. No worker HTTP routes or production service-identity authentication
were added. Real queue delivery and cloud permission separation remain pending.

### Local outbox reconciliation

Trusted dispatcher code can inspect delivery metadata and reconcile pending
records without executing or sending anything:

```python
from handwriting_grader_cloud.outbox import OutboxReconciler

reconciler = OutboxReconciler(control)
status = reconciler.status(dispatcher_principal, limit=20)
page = reconciler.reconcile(dispatcher_principal, limit=20)
next_cursor = page["next_cursor"]
```

Both methods require `JobDispatcher`, use protected tenant index records and
accept a strict 1-50 row limit and opaque UUID cursor. Pass `cursor=next_cursor`
when paging; this progresses past unchanged current rows rather than repeatedly
inspecting the first page. Status contains opaque job/message IDs and hold
metadata, not student content. It describes delivery state, not full artifact
validation or execution readiness.

Reconciliation checks the immutable intent/index/hash and current approved
binding/checkpoint metadata. `CURRENT` means those metadata checks pass; actual
file bytes and pinned-engine preflight are still rechecked before execution.
Stale pending snapshots receive a `STALE` hold; malformed/mismatched control
records receive `QUARANTINED`. Unknown transient errors propagate without
manufacturing a permanent hold.

Each hold has its own hash, dispatcher identity and server UTC time. The original
intent, outbox, exam and human approval history remain unchanged. Held entries
are excluded from pending delivery, and dispatch rechecks the hold atomically.
Holds survive restart, are idempotent and have no automatic release/repair path.
Cancellation remains a separate Teacher action and can cancel a stale held job.
Already assigned or cancelled records are not held by this pending-only reconciler.
This is not a queue poison-message consumer, automatic retry loop, scheduler,
new HTTP route, worker authentication boundary or paid-stage permission.

### Bounded simulated delivery

Trusted internal dispatcher code can exercise the local delivery contract:

```python
from handwriting_grader_cloud.delivery import OfflineDispatcher, SimulatedQueue

queue = SimulatedQueue()
dispatcher = OfflineDispatcher(control, queue)
job_id = job["intent"]["id"]
message_id = job["intent"]["message_id"]
delivery = dispatcher.dispatch(
    dispatcher_principal, job_id, message_id, worker_principal, attempt_id=uuid4()
)
```

The user-approved policy is **three send attempts total**, with server-clock
waits of **5 seconds then 30 seconds** after unconfirmed outcomes. Calls before
the deadline return the persisted wait state without sending. There is no timer,
sleep/retry loop or queue consumer; invoke the next attempt explicitly with a
new UUID while keeping the original job/message IDs and recipient.

Send reservations use the five-minute server-owned claim default, separate from
execution claims. A live send cannot be duplicated by another process. Reusing
its nonce does not resend or extend the reservation. A crash leaves a durable
`SENDING` watermark; after expiry a new nonce can resume within the remaining
attempt limit and backoff. Late/replaced receipts cannot grant worker access.

Confirmed enqueue and worker assignment commit atomically after rechecking the
current approved snapshot and attempt. `DELIVERED` means the simulated enqueue
was acknowledged, not that validation/grading completed. Known confirmations
are reused without resending. Lost acknowledgements may produce duplicate
accepted messages; the same scoped job and fenced executor prevent stale result
publication, not necessarily overlapping CPU work after expiry.

Three unconfirmed or expired attempts produce an immutable `DELIVERY_REVIEW`
hold and remove the entry from pending delivery. No fourth send, automatic
release or fabricated success follows. Unexpected exceptions preserve an unknown
in-flight watermark instead of pretending delivery failed safely. Human review,
intent bytes, approval history and execution authority remain unchanged.

Do not use the legacy `acknowledge_dispatch` path for a managed send; it cannot
bypass the reserved recipient or manufacture a delivery receipt. Existing
legacy assignments remain supported but are not proof of transport delivery.

`SimulatedQueue` is an **in-memory synthetic buffer**, not durable Azure storage.
SQLite send records survive restart; the buffer does not. Tests preserving the
same buffer demonstrate control recovery, not production queue durability.
There is no real queue adapter, service identity, HTTP dispatcher API, scheduler
or permission to retry paid model calls. Inspect history with
`dispatcher.status(dispatcher_principal, job_id)`.

### Fenced offline execution

Trusted internal control/worker code can explicitly run the requested check:

```python
from pathlib import Path

from handwriting_grader_cloud.execution import OfflineValidationExecutor

job_id = job["intent"]["id"]
message_id = job["intent"]["message_id"]
control.acknowledge_dispatch(dispatcher_principal, job_id, message_id, worker_principal)
executor = OfflineValidationExecutor(control, Path(".local/validation-workspaces"))
result = executor.run(worker_principal, job_id, message_id, attempt_id=uuid4())
```

The stage verifies original file hashes, mapped engine approvals and real
PDF/roster/rubric/attendance preflight using the pinned engine. It does not read
handwriting, grade, invoke approval actions, configure a model or call Azure.
Temporary private workspaces are constructed only from scoped worker artifacts
and removed after execution; workers never impersonate a Teacher.

A server-owned claim reserves one attempt for **five minutes**. Give each new
worker/process attempt its own UUID; duplicate claim retries preserve the
original deadline. Another live attempt is rejected, even when both processes
share one managed identity. Expiry automatically permits a replacement on its
next call, with a higher fencing number. It does not kill the old process,
guarantee no overlapping CPU work after expiry, or schedule a retry by itself.
Five minutes is a starting default, not a production capacity benchmark or
an AI billing limit. There is no claim renewal in this increment.

`executor.cancel(principal, exam_id, job_id)` requires the current owner Teacher
and works even after input changes. Cancellation revokes the claim, blocks
dispatch/worker reads and preserves the intent and audit time. It is idempotent;
an already completed result cannot be cancelled or overwritten.

Completion atomically checks the current approved snapshot, assigned worker,
attempt, fence, expiry and cancellation. Only one immutable, hash-checked
result commits. Duplicate delivery of a completed current job reuses it without
rerunning validation. `executor.owned_result(principal, exam_id, job_id)` allows
the owner to inspect a historical result after later edits; it is not current
approval or permission to grade. Expired, failed or crashed validation remains
eligible for a replacement attempt, but no queue consumer/scheduler is running.

### One-shot offline coordinator

Server-controlled components sharing the same trusted `OfflineJobControl` can
connect the simulated message to the read-only executor:

```python
from handwriting_grader_cloud.coordinator import OfflineJobCoordinator

coordinator = OfflineJobCoordinator(control, dispatcher, executor)
before = coordinator.owned_status(principal, exam_id, job_id)
result = coordinator.consume(worker_principal, queue.messages[0], attempt_id=uuid4())
after = coordinator.owned_status(principal, exam_id, job_id)
reviewed_result = coordinator.owned_result(principal, exam_id, job_id)
```

This is an explicit one-shot call, not a background consumer, visibility lease,
delete/acknowledgement loop or new HTTP worker route. It accepts only strict
opaque job/message/recipient fields. Body-selected roles, stages, paths,
receipts and execution claims are rejected. The recipient field is not authority:
the actual authenticated `StageWorker`, protected assignment, current job scope
and confirmed delivery record must all match before the executor runs.
Legacy assignment alone or an accepted message with an unconfirmed enqueue
does not authorize consumption. No Teacher/Dispatcher principal is forged.

`owned_status` and `owned_result` require the current owner Teacher and tenant.
Inspection performs no send, retry, execution or automatic approval. Status
separates delivery from validation; live/expired claims, pending retries,
operator holds, cancellation and stale inputs remain visible.
`eligible_for_validation` describes the observed coordinator scope, not a
transferable permission: actual consumption rechecks authority and the live fence.
Concurrent edits produce a stale-view conflict rather than a misleading current view.

A completed result is hash-checked before success is displayed and reused on
duplicate consumption. Later input edits produce `VALIDATED_HISTORICAL`; the
owner may inspect that original result, but it cannot approve the new inputs
or grant grading. Live duplicates cannot bypass execution claims; expired
read-only validation can be replaced under the existing separate execution policy.
The three-send transport cap does not grant paid-call retries. Real queue
storage/consumer recovery, production identities, teacher job UI and all
paid/grading stages remain pending.

### Teacher-owned offline job HTTP access

After current input/attendance/region approvals, explicitly prepare compatible
inputs with `POST /api/exams/{id}/offline-inputs` and `{"confirmed": true}`.
It returns only `checkpoint_id`, `checkpoint_sha256` and `exam_version`, never
a filesystem destination. Request the non-paid check with
`POST /api/exams/{id}/jobs`, supplying that `checkpoint_id`, a stable UUID
`request_id` and `confirmed: true`. Identical replay returns the same job/message
with HTTP 201. These actions do not change the exam version or approval history.

Owned job listing accepts `limit` (1–50, default 20) and an optional UUID cursor.
Lifecycle and result GETs never dispatch, consume or approve anything. Pending
results return `RESULT_NOT_READY` (409); completed results are hash-checked and
remain readable as historical evidence after input edits, not current approval.
Cancellation requires `{"confirmed": true}` and the current quoted exam ETag,
checked inside the cancellation write transaction even when the job is stale.
All six routes enforce the existing owner/tenant Teacher boundary.

Application startup now initializes internal job tables and control components,
but starts no worker, polling or transport. The server-controlled default root
is `offline-workspaces` beside the SQLite database, with `inputs` and `validation`
subdirectories; trusted `create_app(..., workspace_root=...)` callers may override
it. Preparation persists immutable checkpoint references and removes only its
new private workspace directory. HTTP bodies cannot select paths, stages or
workers. No dispatch/consume/run/grading endpoint or browser job UI is included.

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
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --attendance --regions --offline-jobs
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
| List owned exam summaries | `GET /api/exams?limit=20&cursor={optional-uuid}` |
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
| Explicitly prepare approved offline inputs | `POST /api/exams/{id}/offline-inputs` |
| Confirm an offline validation request | `POST /api/exams/{id}/jobs` |
| List owned offline jobs | `GET /api/exams/{id}/jobs?limit=20&cursor={optional-uuid}` |
| Inspect job lifecycle | `GET /api/exams/{id}/jobs/{job}` |
| Read committed validation result | `GET /api/exams/{id}/jobs/{job}/result` |
| Confirm cancellation with current exam ETag | `POST /api/exams/{id}/jobs/{job}/cancel` |

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

## Offline CI

[The validation workflow](.github/workflows/validate.yml) runs locked Python and
frontend checks plus the real synthetic browser workflow on Ubuntu 24.04.
Official actions are pinned to reviewed commit hashes. It requests read-only
repository access, uses no Azure credentials and performs no deployments/model
calls. Only synthetic JUnit XML is uploaded, not databases or browser traces.

Workflow lint and the equivalent local commands pass. Hosted offline validation
also passed for published `9316676`:
[observed run](https://github.com/wongcyrus/azure-handwriting-grader-foundry/actions/runs/45528244778).
This does not verify the newer local execution/reconciliation increments.
Production release/deployment CI remains a separate milestone.

## Local teacher canvas

With the synthetic API running, create an explicitly fake exam:

```sh
uv run --frozen --extra dev --extra engine python tools/seed_canvas.py
cd apps/web
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. Enter the matching synthetic development token and
choose **Show my exams**, then select and load an owned exam. The emitted exam
ID remains an optional developer shortcut. Listing returns only owned summaries,
up to 50 per request, with a UUID keyset cursor. Ordering is by UUID, not creation
time; refresh the listing to see new items before the current cursor.
The seed creates synthetic input
attestations for a demo, not evidence that a real teacher examined real scans.
Never use real student data or real identity tokens. Tokens remain in browser
memory only; refreshing signs out. Production Entra login is not implemented.

Alternatively enter a new title and choose **Create new exam**. Explicitly save
scan-order/common-layout confirmations, upload PDF scans, XLSX roster/rubric and
optional complete attendance CSV, then validate. Inspect every roster/status row
and the full rubric criteria before confirming the input snapshot. Attendance
CSV requires an independent confirmation. These actions never start grading.
Changing inputs explicitly invalidates current approvals while retaining history.

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
