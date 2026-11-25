# Implementation and test handoff

This file is the persistent checklist for any agent continuing this application.
Read it with [the full plan](implementation-plan.md), [README](../README.md) and
[agent instructions](../AGENTS.md). Update it after each verified increment.

## Current checkout and publication

- Repository: `wongcyrus/azure-handwriting-grader-foundry`.
- Initial docs baseline: `a662755538d079f896a7ee5a6306a3c84f4c6a12`.
- Published after explicit push approval through `9316676`: foundation `e8ad9cf`,
  attendance `708cff1`, region review `9d05ab0`, canvas `9f8e2f0`, owned selection
  `184875d`, input setup `bff8e5b`, offline CI `7eb4ed8`, browser edges `66bc1eb`,
  workspace hydration `0af4d51`, engine mapping `ed07852` and job control `9316676`.
- Fenced execution/cancellation is committed locally as `8152657` after explicit
  approval, not pushed. Outbox reconciliation is committed locally as `9631574`,
  also not pushed. Simulated delivery is committed locally as `cd6795f`, also
  not pushed. Consumer/lifecycle is committed locally as `48f3336`, not pushed.
  New teacher job HTTP code and this handoff remain uncommitted
  pending review; further commit/publication is not authorized.
- A fresh GitHub clone contains the application through `9316676`, not the newer
  local execution/reconciliation/delivery/consumer increments. Continue in this worktree for those.
- Engine pin: `3b155f9232cb0730587d89677c932ea049dd7f71`.
- New cloud dependencies belong here, not in the engine's default installation.
- No Azure resources, paid inference, email or real student uploads authorized.

## Implemented versus planned

| Area | Current state |
|---|---|
| Auth | Local signed-JWT tests, strict delegated Entra token checks, explicit synthetic dev mode |
| Exam access | Owner/tenant checks; no co-teacher/admin impersonation path |
| Exam discovery | Owned summaries only, bounded UUID cursor paging and browser selection |
| State/storage | SQLite local reference, optimistic ETags, retained artifacts and history |
| Human inputs | Explicit scan order/common layout, snapshot-bound teacher attestation |
| Engine bridge | Offline XLSX/PDF/roster/rubric preflight; provenance/integrity and revalidation |
| Offline review workspace | Owner-scoped hydration, stable config/region paths and byte-identical recovery from immutable local checkpoint references |
| Engine input approval mapping | Explicit control-owned projection of current API attestations; original bytes/times/revision, pinned read-only validation and stable recovery; no paid/job authority |
| Offline validation intents/outbox | Explicit confirmed owner requests, immutable idempotent intent + atomic outbox, trusted dispatcher assignment and scoped worker reads; no queue or paid stage |
| Offline validation execution | Internal read-only pinned-engine checks, five-minute per-attempt fenced claims, stale-safe teacher cancellation and immutable/reused results; no scheduler, HTTP worker auth or paid stage |
| Local outbox reconciliation | Trusted dispatcher tenant-scoped cursor inspection, immutable stale/invalid holds, idempotent/race-safe pending cleanup; no actual transport or automatic repair |
| Simulated delivery | Durable fenced send watermarks, stable recipient/message, three attempts with 5/30-second waits and exhaustion review; no real queue, background consumer or scheduler |
| Offline coordinator | One-shot strict-envelope/confirmed-delivery consumption and owner-only lifecycle/historical result inspection; no background consumer or paid work |
| Teacher offline job HTTP | Confirmed mapped-input preparation/request/cancellation, owner-indexed bounded listing and lifecycle/historical results; current exam ETags, no worker execution route or browser job UI |
| Attendance | Optional complete CSV upload, status preview and independent teacher attestation; production acceptance pending |
| Region review | First-present-script JPEG template, actual pixel dimensions, validated drafts and separate geometry attestation |
| Local teacher canvas | React/TypeScript pointer/keyboard editing, CSS/zoom/DPR conversion, page review, approval and explicit conflict recovery |
| Production Blob/Queue, budgets/paid job execution | Not implemented |
| Skills/Foundry protocol/hosting | Not implemented |
| Teacher setup/input review | Local creation, raw uploads, layout settings, full roster/rubric/status preview and explicit input/attendance approval |
| Score UI and production login | Not implemented; all browser flows remain synthetic localhost only |
| Offline CI | Pinned-action workflow linted; equivalent local commands passed; hosted run passed for published `9316676`, not newer local changes |
| Terraform/release/cloud deployment | Not implemented |
| Grading/reports/delivery | Not implemented; no paid or grading endpoint |

Input review does not authorize grading. PDF counts do not prove correct scan
order/identity. Template rendering honors embedded PDF rotation but does not
validate orientation/alignment/sequence of all scripts. Preserve the engine's
downstream checks when integrating grading.

## Reproducible validation commands

Run from the application root:

```sh
uv sync --extra dev --extra engine
uv run --frozen --extra dev --extra engine pytest
uv run --frozen --extra dev --extra engine ruff check .
uv run --frozen --extra dev --extra engine ruff format --check .
uv run --frozen --extra dev --extra engine python tools/smoke_review.py
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --attendance
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --regions
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --attendance --regions
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --regions --offline-jobs
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --attendance --regions --offline-jobs
```

Frontend commands from `apps/web` (own reviewed manifest/lockfile):

```sh
npm ci
npm run build
npm run check
npm test
npm run test:browser
```

Browser tests require the host's Google Chrome. Ports 18765/18766 must be free;
the runner never reuses an unrelated server. Seed data and approvals are explicitly
synthetic, not evidence of real human review or deployment.

For workflow changes, also run:

```sh
actionlint .github/workflows/validate.yml
```

The observed local validator was actionlint 1.7.12, installed only after a missing
tool error and checked against its official release SHA-256. The Ubuntu 24.04
runner inventory lists Chrome, but hosted execution still requires publication.

Focused selectors:

```sh
uv run --frozen --extra dev --extra engine pytest tests/test_preflight_gates.py tests/test_engine_preflight.py
uv run --frozen --extra dev --extra engine pytest -m engine
uv run --frozen --extra dev --extra engine pytest tests/test_attendance.py
uv run --frozen --extra dev --extra engine pytest tests/test_region_review.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_workspace.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_engine_workspace.py tests/test_workspace.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_jobs.py tests/test_engine_workspace.py tests/test_workspace.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_execution.py tests/test_jobs.py tests/test_engine_workspace.py tests/test_workspace.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_outbox.py tests/test_jobs.py tests/test_execution.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_delivery.py tests/test_outbox.py tests/test_jobs.py tests/test_execution.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_coordinator.py tests/test_delivery.py tests/test_outbox.py tests/test_jobs.py tests/test_execution.py tests/test_repository.py
uv run --frozen --extra dev --extra engine pytest tests/test_job_api.py tests/test_api.py tests/test_auth.py tests/test_repository.py tests/test_coordinator.py tests/test_execution.py
uv run --frozen --extra dev --extra engine pytest tests/test_api.py tests/test_auth.py tests/test_repository.py
```

Engine regression, from its own checkout/environment:

```sh
uv run --frozen python -m unittest discover -s tests -p test_workflow.py -v
```

The `engine` marker needs the optional engine extra. Do not report a full pass
when those tests are skipped. Core state/auth tests deliberately use injected
test doubles; production entrypoints use `EngineInputValidator`.

Raw test results can be retained under ignored `.local/test-results/`:

```sh
uv run --frozen --extra dev --extra engine pytest --junitxml=.local/test-results/pytest.xml
```

## Last verification

Previous increment: 43 application tests, lint/format, live HTTP synthetic review
and 2 pinned-engine workflow tests passed on 2026-11-24.

Foundation/preflight: 73 tests (53 core + 20 real-engine) verified at
2026-11-24T15:00:39Z, then committed as `e8ad9cf`.

Attendance: 101 tests (53 core + 48 real-engine) verified at
2026-11-24T15:20:24Z, then committed as `708cff1`.

Region review: 144 tests and four HTTP smoke modes verified at
2026-11-24T15:30:54Z, then committed as `9d05ab0`.

Canvas: 144 Python, 6 geometry and 14 browser tests verified at
2026-11-24T15:44:36Z, then committed as `9f8e2f0`.

Owned-exam selection: 155 Python and 16 browser tests verified at
2026-11-24T15:50:54Z, then committed as `184875d`.

Input setup/review verified at **2026-11-24T16:00:52Z**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_region_review.py tests/test_repository.py` | 44 passed |
| `pytest tests/test_exam_listing.py` | 11 passed |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 155 passed, no skips/failures/errors; 65 core and 90 real-engine cases |
| `npm run build` | Strict TypeScript and production asset build passed |
| `npm run check` | TypeScript and Prettier passed |
| `npm test` | 6 geometry cases passed |
| `npm run test:browser` | 20 real Chrome/API cases passed; DPR 1 and 2 |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 25 Python files |
| `python tools/smoke_review.py` | Passed; live HTTP with real synthetic PDF/XLSX and clean shutdown |
| `python tools/smoke_review.py --attendance` | Passed; explicit present/absent preview, present-only PDF count and two teacher attestations |
| `python tools/smoke_review.py --regions` | Passed; native JPEGs, canonical draft, separate region attestation |
| `python tools/smoke_review.py --attendance --regions` | Passed; combined flow, three distinct teacher attestations |
| Documentation links/fences and test selectors | Passed; 70 executable selectors |
| `git diff --check` | Passed |

Raw JUnit report: ignored `.local/test-results/pytest.xml`. No inference, Azure
deployment or live Entra authentication was tested.

The initial browser run found an exact-label test locator mismatch for Zoom;
using its accessible combobox role fixed the locator. All pointer cases then
passed, followed by the full 14-case run. No failed case is reported as passed.
Browser services stopped: ports 18765/18766 were verified closed afterward.
All smoke commands clean up their own localhost server and temporary files.
No Azure resources were deployed.
Input test discovery initially exposed incorrectly nested new test declarations;
they were moved to file scope, then all four targeted input cases and the full
20-case browser suite passed.

### Browser input-edge verification

Verified at **2026-11-24T16:13:40+00:00**. No production implementation changed.

| Check actually run | Result |
|---|---|
| `npm run build` | Strict TypeScript and production asset build passed |
| `npm run check` | TypeScript and Prettier passed |
| `npm test` | 6 geometry cases passed |
| `npm run test:browser` | All 26 real Chrome/API cases passed, including six new cases across DPR 1/2 |
| Browser JUnit and shutdown check | 26 cases, no failures/errors/skips; ports 18765/18766 closed |

The initial focused command
`npm run test:browser -- --grep 'legacy preview|stale input settings'`
passed four legacy cases but failed two conflict cases because an exact-label
locator did not find the Pages per student select. The accessible combobox-role
locator fixed the test; the full suite subsequently passed all six new cases.
No runtime bug or approval bypass was found by these cases.

Legacy fixtures omit either `attendance_review` or `rubric_review` from a
test-only browser GET response. They do not forge server approval records or
replace the engine. Revalidation uses the real authenticated API and pinned
engine, restores both previews and resets confirmation. Persisted approval
history remains unchanged and no browser approval request is sent.

Conflict coverage verifies a real stale-ETag 409, preservation of local edits,
no overwrite of the winning server snapshot, cancellation without a reload,
and explicit discard/reload adopting current settings and clearing the error.
Python sources are unchanged; the earlier 155-case pytest result above is
retained, not presented as a new Python run for this browser-only increment.

### Offline review-workspace verification

Verified at **2026-11-24T16:29:22+00:00**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_workspace.py tests/test_repository.py` | 30 passed before adding the final restore-race case |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 184 passed, no failures/errors/skips; 68 core and 116 real-engine cases, including 26 workspace cases |
| `pytest --collect-only -q -m engine` | Confirmed 116 engine-marked cases without rerunning tests |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 27 Python files |
| `python tools/smoke_review.py` | Passed; live synthetic default input workflow and clean shutdown |
| `python tools/smoke_review.py --attendance --regions` | Passed; live explicit attendance plus native template/geometry workflow and clean shutdown |
| Documentation links/fences, selectors and `git diff --check` | Passed; 83 executable Python selectors |

The initial style check caught one long SQL string; it was split before test
execution. Test assertions were corrected to use `ApplicationError.status`
before the focused suite. The restore-race case was then added and covered by
the full 184-case run. No test failure is recorded as a pass.

Raw Python JUnit remains at ignored `.local/test-results/pytest.xml`.
Frontend sources/contracts are unchanged; the prior 26 browser and 6 geometry
results are retained, not claimed as new frontend runs for this backend increment.
No dependencies changed or were restored. No inference, deployment or hosted CI
execution occurred.

### Explicit engine-input mapping verification

Verified at **2026-11-24T16:42:19+00:00**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_engine_workspace.py tests/test_workspace.py tests/test_repository.py` | 48 passed; real mapping plus prior workspace/repository regressions |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 201 passed, no failures/errors/skips; 68 core and 133 engine cases, including 17 new mapping cases |
| `pytest --collect-only -q -m engine` | Confirmed 133 engine-marked cases without rerunning tests |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 28 files |
| Documentation links/fences, selectors, JUnit and `git diff --check` | Passed; 89 executable Python selectors |

The first full-check command stopped at a Python code-fence formatting issue
in the preceding README example, before pytest ran. That example was corrected
while updating the bridge documentation; the subsequent complete suite passed.
The initial focused 48-case run passed without test failures.

API routes, frontend code and repository schema are unchanged in this increment.
Prior live HTTP, 26 browser and 6 geometry results remain historical evidence,
not new runs. Original API approval IDs/actors/times and document version/history
are preserved; mapped inputs are not job or paid-stage permission.
No engine approval actions, grading, model clients or network calls are allowed
in the mapping cases. No dependencies were changed/restored, and nothing was
pushed, deployed or tested against hosted CI.

### Offline job-intent/outbox verification

Verified at **2026-11-25T01:09:04+00:00**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_jobs.py tests/test_engine_workspace.py tests/test_workspace.py tests/test_repository.py` | 70 passed before adding final cross-exam/context-race cases |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 225 passed, no failures/errors/skips; 68 core and 157 engine cases, including 24 job-control cases |
| `pytest --collect-only -q -m engine` | Confirmed 157 real-engine cases without rerunning tests |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 31 files |
| Documentation links/fences, selectors, JUnit and `git diff --check` | Passed; 103 executable Python selectors |

All initial focused cases passed; two additional scope/race cases were then
covered by the complete suite. Raw JUnit remains at ignored
`.local/test-results/pytest.xml`. No dependency changes/restoration occurred.
API routes, authentication and frontend code are unchanged; prior live HTTP,
26 browser and 6 geometry results remain historical, not new runs.

The new tables are initialized only by internal `OfflineJobControl`, not by a
new public API. All jobs are the fixed offline input-validation stage. Tests
prohibit grading and engine-marked model-client/network guards remain active.
Neither admission nor dispatch acknowledgement executes a job or sends a queue
message. No worker HTTP authentication, leases/fencing, result writes, paid
consent/budgets, cloud resources or hosted CI were implemented/tested.

### Fenced offline execution verification

Verified at **2026-11-25T01:33:47+00:00**:

| Check actually run | Result |
|---|---|
| Focused execution/job/workspace/repository pytest suite | 98 passed after correcting the pending-cancellation assertion |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 253 passed, no failures/errors/skips; 68 core and 185 real-engine cases, including 28 new execution cases |
| `pytest --collect-only -q -m engine` | Confirmed 185 engine-marked cases without rerunning tests |
| `ruff check .` and `ruff format --check .` | Passed; 33 files |
| Documentation links/fences and named Python selectors | Passed; 119 executable selectors |

The first focused run reported 94 passed and one test failure: a cancelled,
never-dispatched job correctly returned `NOT_FOUND` to an unassigned worker,
not `JOB_CANCELLED`. The assertion was corrected without weakening access
checks. The next focused run passed all 98 cases. An intermediate full run
passed 251 cases; two final expiry/provenance cases were then added and the
complete 253-case suite passed. No failure is reported as a pass.

Five minutes is the confirmed initial server-clock claim default, not a measured
production capacity guarantee. Tests cover exact expiry, simultaneous claims,
recovery, overlapping old/new validation, transactional rollback and immutable
result reuse. Expiry/cancellation does not forcibly stop a native parser.
Replacement is eligible on the next attempt; no queue consumer/scheduler or
claim renewal is implemented. Both before/after validation provenance checks
must pass, and only the current live fence/current snapshot can commit.

Raw JUnit remains at ignored `.local/test-results/pytest.xml`. API routes,
authentication and frontend sources are unchanged; previous live HTTP,
26 browser and 6 geometry results remain historical, not new runs.
No dependencies were changed/restored. No grading, approval actions, model
clients, network calls, real student data, cloud resources, push or new commit
were used. New execution code/tests and this handoff await separate review.

### Published offline CI evidence

Observed at **2026-11-25T02:02:25+00:00**:
[run 45528244778](https://github.com/wongcyrus/azure-handwriting-grader-foundry/actions/runs/45528244778)
completed successfully for published `9316676d6fcdce3ad9e08cd49fe1ed7732c3e0f8`.
Observed successful steps include Python checks, both offline HTTP smoke flows
and frontend build/check/geometry/browser validation. This is hosted evidence
for `9316676`, not the newer local execution/reconciliation changes. No hosted
test count is inferred from local results. No deployment/model calls were added.

### Local outbox reconciliation verification

Verified at **2026-11-25T02:02:25+00:00**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_outbox.py tests/test_jobs.py tests/test_execution.py tests/test_repository.py` | 82 passed after the integrity classification fix |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 278 passed, no failures/errors/skips; 68 core and 210 real-engine cases, including 25 new outbox cases |
| `pytest --collect-only -q -m engine` | Confirmed 210 real-engine cases without rerunning tests |
| `ruff check .` and `ruff format --check .` | Passed; 35 files |
| Final JUnit, documentation links/fences, selectors and `git diff --check` | Passed; 278 cases with no failures/errors/skips and 131 executable selectors |

The first focused command reported 79 passed and one failure: corrupt checkpoint
metadata raised the repository's `WORKSPACE_INTEGRITY` rather than
`JOB_INTEGRITY`. The reconciler was corrected to quarantine that known integrity
failure, while unknown/transient errors still propagate. Two concurrent/audit
scope cases were then added. The focused 82-case and full 278-case runs passed;
no earlier failure is claimed as a pass.

The hold and its audit hash are separately persisted under a write transaction.
Immutable intents, human review/version/history and worker claims are not
rewritten. Tests cover strict paging/tenant/role checks, current/stale/invalid
records, interruption rollback, protected index consistency, concurrent
reconciliation and assignment/cancellation/input races. Holds have no release
or automatic repair path. This does not implement transport retry caps/backoff,
a queue poison consumer, actual delivery, scheduling or paid execution.

Raw Python JUnit remains at ignored `.local/test-results/pytest.xml`. No
dependency manifests were changed or packages restored locally. API routes,
authentication and frontend sources are unchanged; prior local browser/geometry
evidence is historical, not a new local run. This reconciliation increment
remains uncommitted and unpushed pending separate review.

### Bounded simulated delivery verification

Verified at **2026-11-25T02:17:31+00:00**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_delivery.py tests/test_outbox.py tests/test_jobs.py tests/test_execution.py tests/test_repository.py` | 109 passed; the initial 105-case run also passed before four final boundary cases |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 305 passed, no failures/errors/skips; 68 core and 237 real-engine cases, including 27 delivery cases |
| `pytest --collect-only -q -m engine` | Confirmed 237 real-engine cases without rerunning tests |
| `ruff check .` and `ruff format --check .` | Passed; 37 files |
| Final JUnit, documentation links/fences, selectors and `git diff --check` | Passed; 305 cases with no failures/errors/skips and 149 executable selectors |

The user explicitly approved three total delivery attempts, waits of 5 and
30 seconds, then operator review. Tests use an injected server clock, not sleep.
Send watermarks commit before the local transport call; confirmation and worker
assignment commit together only for the live attempt/current approved snapshot.
Unconfirmed acceptance may duplicate buffered messages but known validation
results are reused. Expired/unknown sends still count toward the same hard cap.
Exhaustion and its immutable hold recover without a fourth send after write failure.

All focused/full checks passed. No dependency manifests were changed or packages
restored locally. Existing engine-marked network/model guards and explicit
grading/approval prohibitions apply. The one queue-to-executor case runs actual
pinned-engine read-only validation and verifies result reuse without reexecution.

Raw JUnit remains at ignored `.local/test-results/pytest.xml`. Frontend, HTTP
routes and authentication are unchanged; older local/hosted browser evidence
remains historical, not a new run for this increment. `SimulatedQueue` is not
durable message storage and no consumer, scheduler, real adapter, cloud resources
or paid-stage retries are enabled. This increment is uncommitted and unpushed.

### One-shot consumer and lifecycle verification

Verified at **2026-11-25T02:27:15+00:00**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_coordinator.py tests/test_delivery.py tests/test_outbox.py tests/test_jobs.py tests/test_execution.py tests/test_repository.py` | 141 passed; initial 138-case run also passed before three final authority/expiry cases |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 337 passed, no failures/errors/skips; 68 core and 269 real-engine cases, including 32 coordinator cases |
| `pytest --collect-only -q -m engine` | Confirmed 269 real-engine cases without rerunning tests |
| `ruff check .` and `ruff format --check .` | Passed; 39 files |
| Final JUnit, documentation links/fences, selectors and `git diff --check` | Passed; 337 cases with no failures/errors/skips and 165 executable selectors |

After adding three final cases, lint caught one unsorted import block and stopped
before pytest ran. Ruff's import fix was applied; the subsequent focused/full
commands passed. No test failure or stopped command is reported as a pass.

Positive with/without-attendance cases use actual confirmed simulated delivery
and pinned-engine validation, not fake validators. Tests cover strict envelopes,
authenticated assignment and receipt scope, no legacy/unconfirmed bypass,
live claims and expiry, duplicate result reuse, owner/tenant checks, held/stale/
cancelled/historical states, corrupt results and snapshot-inspection races.
Inspection never sends, consumes, retries or approves automatically.

Raw JUnit remains at ignored `.local/test-results/pytest.xml`. No dependencies
were changed/restored; existing network/model guards and approval/grading
prohibitions remain active. HTTP routes, authentication and frontend are
unchanged, so earlier browser/HTTP evidence is historical, not a fresh run.
The coordinator is internal one-shot code, not production queue polling,
durable acknowledgements, service identity or paid execution. New code/tests
and this handoff await review; nothing in this increment was committed/pushed.

### Teacher-owned offline job HTTP verification

Verified at **2026-11-25T02:47:33+00:00**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_job_api.py tests/test_api.py tests/test_auth.py tests/test_repository.py tests/test_coordinator.py tests/test_execution.py` | 147 passed |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 377 passed, no failures/errors/skips; 68 core and 309 real-engine cases, including 40 new job HTTP cases |
| `pytest --collect-only -q -m engine` | Confirmed 309 real-engine cases without rerunning tests |
| `ruff check .` and `ruff format --check .` | Passed; 40 files |
| `python tools/smoke_review.py` | Passed; existing live authenticated synthetic input flow |
| `python tools/smoke_review.py --regions --offline-jobs` | Passed; no-CSV preparation/replay/list/status/pending-result rejection and stale-safe cancellation |
| `python tools/smoke_review.py --attendance --regions --offline-jobs` | Passed; same job flow with explicit CSV/three retained attestations |
| `actionlint .github/workflows/validate.yml` | Passed using the existing reviewed cached actionlint 1.7.12 binary |
| Final JUnit, documentation links/fences, selectors and `git diff --check` | Passed; 377 clean cases and 177 executable selectors |

Initial focused lint stopped before pytest because of one unsorted test import
block. Ruff fixed it; all 147 focused cases subsequently passed. `actionlint`
was not on PATH, so the already reviewed session-cached binary was invoked by
absolute path; no tool was installed or dependency restored. No stopped command
is reported as a pass.

HTTP preparation removes only its new private directory after persisting the
mapped checkpoint, and returns no path. Mutations require literal confirmation
and quoted current exam ETags. Cancellation rechecks the current version under
its write transaction independently of the old job binding. Listing uses a
protected owner/tenant/exam index and bounded UUID paging. Results are actual
internally produced pinned-engine evidence; owner GETs never execute work and
historical evidence cannot authorize new inputs.

Application startup now initializes internal job tables/control components but
starts no delivery, consumer or worker. The workflow's combined smoke command
now covers job HTTP access; hosted evidence still belongs only to `9316676`.
Frontend sources were not changed or rerun; previous browser/geometry results
remain historical. All live smoke servers cleanly stopped and their temporary
synthetic data was removed. No paid/model calls, engine approval actions,
grading, cloud deployment, real student records or push occurred.

The preceding coordinator increment was committed after explicit approval as
`48f3336`, not pushed. This HTTP increment and handoff remain uncommitted pending
review. Next bounded work is the teacher job UI, not worker HTTP execution,
production queues or paid-stage admission.

## Local foundation regression cases

- [x] `tests/test_auth.py::test_valid_delegated_token`: signed delegated token accepted.
- [x] `tests/test_auth.py::test_invalid_tokens_fail_closed`: issuer/audience/tenant,
  expiry, object ID, scope, app-only identity and malformed role claims rejected.
- [x] `tests/test_auth.py::test_wrong_signature_and_missing_token`: invalid signature,
  absent or malformed token rejected.
- [x] `tests/test_auth.py::test_development_authentication_requires_explicit_long_token`.
- [x] `tests/test_api.py::test_exam_access_and_approval_are_scoped`: other teacher,
  tenant, worker, administrator-only and unauthenticated access denied.
- [x] `tests/test_api.py::test_missing_authentication_and_forged_identity_are_rejected`.
- [x] `tests/test_api.py::test_mutations_require_current_bounded_etag`.
- [x] `tests/test_api.py::test_missing_inputs_and_scan_confirmation_block_review`.
- [x] `tests/test_api.py::test_approval_requires_literal_confirmation`.
- [x] `tests/test_api.py::test_wrong_snapshot_and_unreviewed_state_cannot_be_approved`.
- [x] `tests/test_api.py::test_review_survives_restart_and_records_authenticated_identity`.
- [x] `tests/test_api.py::test_changed_inputs_invalidate_approval_but_keep_old_content_and_history`.
- [x] `tests/test_api.py::test_layout_changes_invalidate_review`.
- [x] `tests/test_api.py::test_stale_tab_cannot_overwrite_or_duplicate_approval`.
- [x] `tests/test_api.py::test_artifact_access_does_not_cross_exam_or_owner`.
- [x] `tests/test_api.py::test_oversize_empty_and_invalid_kind_uploads_do_not_change_state`.
- [x] `tests/test_api.py::test_layout_counts_are_bounded_integers`.
- [x] `tests/test_repository.py::test_compare_and_swap_conflict_rolls_back_artifact`.
- [x] `tests/test_api.py::test_no_paid_or_grading_endpoint_exists`.

## New preflight and revalidation cases

- [x] `tests/test_preflight_gates.py::test_validation_failure_does_not_enter_review`.
- [x] `tests/test_preflight_gates.py::test_approval_revalidates_instead_of_trusting_saved_preflight`.
- [x] `tests/test_preflight_gates.py::test_corrupt_stored_bytes_block_approval`.
- [x] `tests/test_preflight_gates.py::test_legacy_review_without_preflight_cannot_be_approved`.
- [x] `tests/test_preflight_gates.py::test_missing_engine_fails_closed_before_parsing`.
- [x] `tests/test_preflight_gates.py::test_missing_or_changed_engine_provenance_is_rejected`.
- [x] `tests/test_preflight_gates.py::test_common_layout_requires_explicit_confirmation`.
- [x] `tests/test_engine_preflight.py::test_real_files_are_validated_and_approval_keeps_provenance`:
  real synthetic PDF/XLSX; string IDs `001`/`002`; counts/rubric and approval.
- [x] `tests/test_engine_preflight.py::test_empty_or_mismatched_pdf_does_not_enter_review`.
- [x] `tests/test_engine_preflight.py::test_corrupt_pdf_is_rejected`.
- [x] `tests/test_engine_preflight.py::test_roster_errors_are_rejected_by_existing_engine`:
  missing sheet/columns, duplicate IDs and empty roster.
- [x] `tests/test_engine_preflight.py::test_malformed_roster_xml_returns_validation_error_not_server_failure`:
  parser exceptions from the new attendance/roster precheck return a validation
  error rather than a server failure.
- [x] `tests/test_engine_preflight.py::test_invalid_or_formula_rubric_marks_are_rejected`.
- [x] `tests/test_engine_preflight.py::test_non_workbook_and_expansion_limit_are_rejected`.
- [x] `tests/test_engine_preflight.py::test_pdf_page_limit_is_enforced`.
- [x] `tests/test_engine_preflight.py::test_engine_pin_change_after_review_blocks_approval`.
- [x] `tests/test_engine_preflight.py::test_workbook_policy_and_parser_errors_fail_closed`:
  macro content, unsupported compression, invalid XML, entry cap and overflowing total marks.
- [x] Real-engine tests prohibit Azure client construction and network connections.
- [x] `tools/smoke_review.py`: live localhost flow with real synthetic files,
  unauthorized rejection, attestation and clean server shutdown.

## Required future cases: not implemented or verified

- [ ] Live tenant registration/token acquisition, revoked grants and deployment auth.
- [ ] Separate API-owned control storage and worker-only artifact permissions.
- [ ] Blob ETag conflict, immutable version reads, partial upload/finalization and retention.
- [ ] Attendance web UI and school-policy acceptance of human presence review.
- [ ] All-script full-page review and orientation/sequence validation; current
  template JPEGs and box validation do not establish these.
- [ ] Hostile-parser resource isolation/timeouts; current local size/archive caps are not a production sandbox.
- [ ] Teacher UI: coordinates under zoom/DPR, stale tabs, bulk preview, keyboard flow.
- [ ] Score review: every row/identity, flagged/failed manual marks, finite ranges.
- [ ] Current verified pricing, consent per paid stage and initial conversational allowance.
- [ ] Parallel budget reservations, unknown usage and administrator pause.
- [ ] Approval + job outbox atomicity; dispatch failure, queue duplicates and poison messages.
- [ ] Production fenced execution, incremental grading checkpoints and unknown provider outcomes.
- [ ] Cooperative cancellation/SIGTERM with synchronous grading thread still active.
- [ ] Real SkillsProvider load/resource read and approved typed tool selection.
- [ ] Prompt injection cannot grant approval or arbitrary paths/tools.
- [ ] Foundry Responses contract, stored background resilience, reentry and session expiry.
- [ ] No model reissue for known committed results; unknown results require a decision.
- [ ] Terraform fmt/validate/plan, identities, image digest, candidate readiness and rollback.
- [ ] Effective guardrail testing under a separately approved paid allowance.
- [ ] Approved-only report generation/downloads and correct child-run provenance.
- [ ] Delivery preview/approval/journal, if later enabled.
- [ ] Teacher quality evaluation and 4/30/50-student capacity/cost benchmarks.
- [ ] Backup/restore, privacy logs, deletion and backup retention.

## Next-agent continuation

1. Run the required commands above and inspect `git status --short`.
2. Do not treat locally committed or untracked implementation as already published.
3. Next bounded task: teacher-owned offline job UI using the verified HTTP
  preparation/request/list/lifecycle/result/cancellation routes, with explicit
  confirmation and current-version conflict handling; no worker
  HTTP authentication or paid-stage admission should be inferred. Preserve
  the approved three-attempt 5/30-second transport policy, separate five-minute
  send/execution fences, immutable reconciliation holds and result reuse.
  A live duplicate cannot start execution; expiry may allow overlapping CPU
  validation but only the current live attempt can publish. Retry eligibility
  does not mean a scheduler/consumer exists. Do not connect real queues,
  add paid stages/model config or execute grading before separate approvals.
4. Acceptance: no tenant/owner enumeration, bounded pagination, no plaintext
  credentials in URL/storage, and no automatic approvals. Preserve unsaved
  changes when switching an exam. Continue real synthetic API/browser testing.
5. Keep the engine's orientation/sequence checks before later grading; page count
  alone cannot establish correct scans or student identity.
6. Add focused positive/negative integration tests and a reproducible smoke path.
7. Update this checklist with observed results and remaining gates.

Cloud resources, paid tests, real student evaluation, commits and publication
remain separate user decisions. M0 school/region/privacy/budget decisions are not
resolved merely because local tests pass.

## Attendance increment cases

- [x] `tests/test_attendance.py::test_present_counts_and_distinct_attendance_approval_are_durable`:
  full roster retained, text IDs preserved, absent not zero, two atomic attestations,
  UTF-8/BOM acceptance, persistence and duplicate submission conflict.
- [x] `tests/test_attendance.py::test_attendance_needs_its_own_literal_confirmation`.
- [x] `tests/test_attendance.py::test_invalid_attendance_cannot_enter_review`:
  omitted/duplicate/unknown IDs, invalid/empty status, no present student, leading
  zero mismatch, padded ID, incorrect/extra headers and invalid UTF-8.
- [x] `tests/test_attendance.py::test_pdf_counts_follow_present_students_not_the_full_roster`.
- [x] `tests/test_attendance.py::test_no_csv_preserves_explicit_all_roster_default`.
- [x] `tests/test_attendance.py::test_changed_attendance_invalidates_both_approvals_without_erasing_history`.
- [x] `tests/test_attendance.py::test_corrupt_attendance_after_review_blocks_both_approvals`.
- [x] `tests/test_attendance.py::test_attendance_preview_and_approval_are_exam_scoped`.
- [x] `tests/test_attendance.py::test_changed_settings_invalidate_both_current_approvals`.
- [x] `tests/test_attendance.py::test_wrong_snapshot_with_current_etag_cannot_approve_attendance`.
- [x] `tests/test_attendance.py::test_concurrent_change_cannot_persist_either_attestation`.
- [x] Live HTTP smoke with `tools/smoke_review.py --attendance`.

## Rendered-page and region-review cases

- [x] `tests/test_region_review.py::test_rendered_template_and_geometry_approval_survive_restart`:
  real native JPEGs, dimension/hash provenance, protected download, snapshot-bound
  geometry approval, restart persistence and duplicate approval conflict.
- [x] `tests/test_region_review.py::test_inputs_must_be_approved_before_rendering`.
- [x] `tests/test_region_review.py::test_invalid_drafts_do_not_change_review`:
  missing/extra/padded page keys, unknown rubric question, bounds, invalid metadata
  labels, float/bool coordinates and duplicate/unknown reviewed indexes.
- [x] `tests/test_region_review.py::test_incomplete_geometry_cannot_be_approved`:
  missing metadata/page review, ID on the wrong page and duplicate canonical aliases.
- [x] `tests/test_region_review.py::test_every_rubric_question_requires_a_region`.
- [x] `tests/test_region_review.py::test_region_approval_requires_literal_confirmation_and_current_hashes`.
- [x] `tests/test_region_review.py::test_edits_invalidate_geometry_only_and_keep_approved_revision`.
- [x] `tests/test_region_review.py::test_input_changes_invalidate_rendered_review`:
  scan/roster/rubric/attendance/settings changes clear previews and current approvals.
- [x] `tests/test_region_review.py::test_region_routes_are_owner_and_tenant_scoped`.
- [x] `tests/test_region_review.py::test_corrupt_inputs_or_images_block_region_approval`.
- [x] `tests/test_region_review.py::test_large_page_is_rejected_before_engine_render`.
- [x] `tests/test_region_review.py::test_render_race_persists_neither_manifest_nor_images`.
- [x] `tests/test_region_review.py::test_pdf_rotation_uses_rendered_dimensions_for_box_bounds`.
- [x] `tests/test_region_review.py::test_template_pixel_limit_is_checked_before_rendering`.
- [x] `tests/test_region_review.py::test_region_mutations_require_etags_and_page_indexes_are_bounded`.
- [x] `tests/test_region_review.py::test_engine_change_after_rendering_blocks_region_approval`.
- [x] `tests/test_repository.py::test_multi_artifact_failure_rolls_back_manifest_and_all_images`.
- [x] Live HTTP smoke with `--regions` and combined `--attendance --regions`.

Native rendering is serialized per process and uses the pinned `prepare_regions`
adapter at 200 DPI. Caps are 4 million pixels/page, 24 million/template and 10 MiB
per JPEG. No engine approval files are materialized and no model endpoint is called.
Process isolation, render timeouts, all-script scan checks and production storage
remain unverified future work.

## Local teacher canvas cases

- [x] `apps/web/src/geometry.test.ts`: zoom-aware mapping, clipped reverse drags,
  zero-width suppression and bounded keyboard movement (6 cases).
- [x] `apps/web/tests/canvas.spec.ts`: real API/native JPEG pointer geometry at
  25%, 50% and 200% zoom, each under DPR 1 and 2.
- [x] Keyboard movement invalidates page review; complete layouts require explicit
  save/confirmation and never auto-approve on page load.
- [x] Stale save preserves local boxes; reapply uses the latest ETag and clears
  review flags. Changed input hashes disable old-coordinate reapplication.
- [x] Token remains memory-only; reload returns to sign-in with empty credentials.
- [x] Strict TS build, Prettier, 14 browser cases and test-service cleanup.
- [ ] Other browsers, touchscreen/rotation gestures, screen-reader evaluation,
  school acceptance, live Entra and deployed SWA/API integration.

Ignored evidence: `.local/test-results/pytest.xml`, `browser.xml`, browser artifacts
and `canvas.sqlite3` (synthetic only). Never publish credentials, real student
records or private traces.

## Owned exam selection cases

- [x] `tests/test_exam_listing.py::test_listing_returns_only_owned_summaries`.
- [x] `tests/test_exam_listing.py::test_cursor_pages_are_bounded_and_do_not_duplicate_exams`.
- [x] `tests/test_exam_listing.py::test_no_owned_exams_returns_an_empty_collection`.
- [x] `tests/test_exam_listing.py::test_invalid_paging_parameters_are_rejected`.
- [x] `tests/test_exam_listing.py::test_listing_requires_authenticated_teacher`.
- [x] `tests/test_exam_listing.py::test_query_parameters_cannot_override_authenticated_identity`.
- [x] Real Chrome selection follows cursor pages, loads an owned exam without
  manual UUID entry and clears summaries/credentials on disconnect (DPR 1/2).
- [ ] Production listing index/Blob adapter, chronological ordering, concurrent
  snapshot pagination and school exam-search UX.

## Browser input setup/review cases

- [x] Create an exam without typing a UUID; new layout confirmations start false.
- [x] Explicit settings save followed by real raw PDF/XLSX uploads and optional
  CSV attendance, through authenticated ETag endpoints.
- [x] Full roster/status table preserves IDs `001`/`002`; absence is not zero.
- [x] Full rubric question text/criteria/marks are shown from the pinned engine.
- [x] Input approval starts unchecked; CSV requires independent attendance
  confirmation. Verify persisted state and one/two attestations, then render.
- [x] Explicitly reopening approved input setup clears current input/region
  approvals and preserves prior history; unsaved boxes are discarded only after
  confirmation.
- [x] Four input workflow cases (CSV/no CSV, DPR 1/2) plus existing browser
  regression: 20 total passed.
- [x] `legacy preview missing attendance_review blocks approval until revalidation`
  and `legacy preview missing rubric_review blocks approval until revalidation`:
  missing either preview blocks approval even after confirmation; real
  revalidation restores the previews and requires a new confirmation.
- [x] `stale input settings preserve edits until explicit discard and reload`:
  conflict preserves local fields, cancel retains edits without a read, and
  confirmed reload adopts the winning settings without overwriting server state.
- [x] Six new cases across DPR 1/2; all 26 browser cases passed.
- [ ] Production direct-Blob uploads, progress/retry UX, editable rubric/roster
  grid, school validation and real Entra sign-in.

## Offline CI verification

- [x] `.github/workflows/validate.yml` passes actionlint 1.7.12.
- [x] Official checkout/setup-node/setup-uv/upload-artifact releases resolved to
  immutable commit SHAs; uv 0.12.17, Python 3.12 and Node 24 selected.
- [x] Read-only contents permission, no persisted Git credentials, no Azure
  credentials/deployment steps and no `pull_request_target` execution.
- [x] Lockfile restore commands, Python/style checks, HTTP smoke, TS/build/style,
  geometry tests and actual synthetic Chrome workflow are represented.
- [x] Local equivalents: current 225 Python, prior 6 geometry and 26 browser
  cases passed; hosted results are not claimed.
- [x] Evidence upload is restricted to synthetic JUnit XML; no raw database,
  browser trace, student record or credential artifact is uploaded.
- [ ] GitHub-hosted workflow execution, branch protection and release/deployment
  workflow. These are not verified by local actionlint.

## Offline approved-review workspace cases

This is the first M3 local bridge slice, not M3 completion or an engine execution
checkpoint. The adapter is internal control code; StageWorker and Administrator
roles cannot use it as teacher identities. Protected cloud job contexts remain
unimplemented.

- [x] `tests/test_workspace.py::test_approved_workspace_survives_replacement_without_invented_approvals`:
  real PDF/XLSX and optional CSV, existing immutable input/image references,
  new repository/service/root, byte-identical files/config/paths, real
  `verify_run` and `check_exam`, unchanged API approval history/version.
  Engine approval remains false; no engine approval files or model config.
- [x] `tests/test_workspace.py::test_workspace_hydration_and_recovery_are_owner_scoped`:
  other teacher/tenant, worker and admin rejected before filesystem writes.
- [x] `tests/test_workspace.py::test_hydration_rejects_missing_or_incompatible_attestations`:
  missing input/region approval, wrong actor/pin, mismatched saved geometry
  and duplicate approval ID rejected.
- [x] `tests/test_workspace.py::test_explicit_attendance_needs_its_separate_current_attestation`.
- [x] `tests/test_workspace.py::test_changed_inputs_and_reapproved_geometry_cannot_restore_old_checkpoint`:
  stale version, reapproved geometry and invalidated inputs cannot replay a checkpoint.
- [x] `tests/test_workspace.py::test_corrupt_input_image_or_checkpoint_file_cannot_be_restored`.
- [x] `tests/test_workspace.py::test_corrupt_checkpoint_metadata_is_rejected_before_filesystem_writes`:
  traversal filename, wrong owner/pin and bad manifest hash rejected, including
  modified metadata with a recomputed checksum.
- [x] `tests/test_workspace.py::test_checkpoint_cannot_be_replayed_against_another_owned_exam`.
- [x] `tests/test_workspace.py::test_hydration_race_publishes_neither_checkpoint_nor_partial_workspace`:
  stale CAS inserts no checkpoint/derived blobs and removes its new workspace.
- [x] `tests/test_workspace.py::test_restore_race_removes_only_the_new_workspace`:
  final version check rejects an intervening edit; original workspace survives.
- [x] `tests/test_workspace.py::test_workspace_root_must_be_private_and_not_a_symlink`.
- [x] `tests/test_repository.py::test_checkpoint_failure_rolls_back_all_new_artifacts`:
  missing/corrupt file references roll back all derived artifacts.
- [x] `tests/test_repository.py::test_existing_checkpoint_cannot_be_replaced`:
  insert-only checkpoint identity; duplicate insertion also rolls back new artifacts.
- [x] Explicit engine approval-file mapping with authoritative API provenance;
  compatible imported rubric bytes and JSON attendance review, not another
  normalization/editing step or inferred human approval.
- [ ] Worker-scoped job context, outbox/leases/fencing, cloud Blob/Queue adapters,
  grading manifests/call watermarks, cancellation and unknown-outcome recovery.
- [ ] Checkpoint retention/garbage collection, disk quotas and production
  process/filesystem isolation. A private local root is not a tenant sandbox.

## Explicit engine input approval mapping cases

Default `hydrate` remains approval-free. Only authenticated control code calls
`prepare_engine_inputs`; checkpoint kind distinguishes this explicit projection.
No engine approval command or grading function is called. Local files do not
replace authoritative API approvals, worker job scope or cost consent.

- [x] `tests/test_engine_workspace.py::test_explicit_engine_input_mapping_preserves_api_authority_and_recovery`:
  with/without CSV, real pinned `approved_inputs`, unchanged API records/version,
  original rubric bytes/artifact reference, original approval times and geometry
  revision, leading-zero attendance IDs, present-only roster and byte-identical
  recovery. Prior review checkpoints still restore without approvals.
- [x] `tests/test_engine_workspace.py::test_engine_input_mapping_and_recovery_require_the_owner`:
  other teacher/tenant, worker and admin rejected without new workspaces.
- [x] `tests/test_engine_workspace.py::test_mapping_cannot_invent_missing_approval_identity_or_time`:
  missing input/region/attendance attestations, naive/invalid time and invalid
  attendance UUID rejected before filesystem writes.
- [x] `tests/test_engine_workspace.py::test_rehashed_engine_approval_tampering_cannot_replace_api_provenance`:
  changed rubric/region approval time or attendance review ID rejected even
  after recomputing checkpoint/file hashes.
- [x] `tests/test_engine_workspace.py::test_review_checkpoint_cannot_be_upgraded_by_changing_its_kind`.
- [x] `tests/test_engine_workspace.py::test_engine_validators_reject_bad_mapping_before_checkpoint_publication`:
  real engine rejects a bad source hash; partial workspace removed and no
  checkpoint published.
- [x] All mapping tests forbid engine `approve_attendance`, `approve_rubric`,
  `approve_regions` and `grade_exam`; engine-marked network/client guards remain.
- [ ] Production worker/execution admission, fenced job scope and outbox delivery,
  approved paid consent/budgets and engine execution/call checkpoints.

## Offline validation job intent/outbox cases

Local `OfflineJobControl` is internal control code, not production worker
authentication or an executor. Worker principals are trusted authenticated
inputs; body-selected roles/recipients are not accepted. Jobs and read grants
are explicitly non-paid; no automatic submission follows human approval.

- [x] `tests/test_jobs.py::test_explicit_offline_job_and_outbox_survive_restart_without_execution`:
  real approved mapped inputs with/without CSV, durable intent/outbox, unchanged
  human approval/version, scoped context and hash-checked roster bytes; no new
  workspace or execution after process replacement.
- [x] `tests/test_jobs.py::test_repeated_request_and_duplicate_dispatch_keep_one_stable_job`:
  same request returns the same job/message, conflicting checkpoint reuse and
  reassignment fail; duplicate acknowledgement preserves original dispatch time.
- [x] `tests/test_jobs.py::test_request_model_cannot_select_paid_stage_or_worker`:
  extra stage/recipient and non-boolean confirmation rejected.
- [x] `tests/test_jobs.py::test_false_confirmation_and_review_only_checkpoint_do_not_admit_jobs`.
- [x] `tests/test_jobs.py::test_job_request_and_owner_read_are_teacher_scoped`.
- [x] `tests/test_jobs.py::test_checkpoint_and_job_ids_cannot_cross_owned_exam_boundaries`.
- [x] `tests/test_jobs.py::test_dispatch_and_worker_grants_do_not_cross_roles_tenants_or_messages`.
- [x] `tests/test_jobs.py::test_worker_artifact_grant_excludes_other_files_and_checks_corruption`.
- [x] `tests/test_jobs.py::test_input_changes_revoke_dispatch_context_and_idempotent_replay`.
- [x] `tests/test_jobs.py::test_worker_context_rechecks_version_after_loading_its_grant`.
- [x] `tests/test_jobs.py::test_job_and_outbox_admission_race_rolls_back_both_rows`.
- [x] `tests/test_jobs.py::test_outbox_insert_failure_rolls_back_the_new_job`.
- [x] `tests/test_jobs.py::test_job_corruption_or_rehashed_paid_stage_cannot_grant_context`.
- [x] `tests/test_jobs.py::test_dispatch_outbox_limits_are_strictly_bounded`.
- [x] Local fenced/expiring execution claims, teacher cancellation and immutable
  read-only validation results; cases below.
- [x] Local stale/invalid pending outbox reconciliation and immutable holds; cases below.
- [x] Bounded simulated transport policy: three total attempts, 5/30-second waits,
  durable unknown-send watermarks and terminal operator review; cases below.
- [ ] Real queue delivery, consumer/scheduler and production queue poison-message handling.
- [ ] Production worker authentication and separate control/artifact permissions,
  cloud job APIs/UI, approved paid budgets/stages and Foundry runtime execution.

## Fenced offline execution cases

These synthetic real-engine cases prohibit approval/grading actions and run
under the engine-marked network/model-client guards. The default five-minute
server-clock claim and expiry replacement apply only to read-only validation.
Tests inject a deterministic timezone-aware clock; they do not sleep or prove
production throughput. No queue consumer, retry scheduler or runtime lease
renewal is implemented.

- [x] `tests/test_execution.py::test_real_readonly_execution_and_immutable_result_survive_restart`:
  with/without attendance, actual engine preflight/approval compatibility,
  unchanged human authority, scoped workspace cleanup and durable result reuse
  without a second validator call or Teacher impersonation.
- [x] `tests/test_execution.py::test_live_claim_retries_do_not_restart_or_extend_attempts`.
- [x] `tests/test_execution.py::test_expiry_replaces_claim_and_fences_old_completion`:
  exact deadline, higher replacement fence, old-attempt rejection and duplicate
  completion returning the original result rather than overwriting it.
- [x] `tests/test_execution.py::test_teacher_cancellation_revokes_claims_and_pending_delivery_even_when_stale`.
- [x] `tests/test_execution.py::test_execution_claim_cannot_cross_worker_roles_or_assignments`.
- [x] `tests/test_execution.py::test_cancellation_and_historical_results_remain_teacher_owned`.
- [x] `tests/test_execution.py::test_attempt_ids_messages_and_caller_lease_fields_are_not_authority`.
- [x] `tests/test_execution.py::test_late_validation_cannot_publish_after_cancellation_change_or_expiry`.
- [x] `tests/test_execution.py::test_replacement_can_finish_before_expired_original_returns`:
  overlapping read-only attempts, only the replacement's immutable result commits.
- [x] `tests/test_execution.py::test_result_insert_and_completion_are_atomic_and_retry_after_crash`.
- [x] `tests/test_execution.py::test_expiry_during_result_transaction_rolls_back_publication`.
- [x] `tests/test_execution.py::test_competing_process_attempts_sharing_identity_have_only_one_live_claim`:
  concurrent SQLite claims after synchronized context reads; one winner.
- [x] `tests/test_execution.py::test_claim_survives_repository_replacement_without_extending_expiry`.
- [x] `tests/test_execution.py::test_changed_engine_pin_blocks_validation_publication`:
  mismatched provenance before parsing or immediately after real validation.
- [x] `tests/test_execution.py::test_corrupt_scoped_artifact_prevents_execution_result`.
- [x] `tests/test_execution.py::test_completed_result_is_integrity_checked_and_remains_historical`.
- [ ] Production parsing isolation, capacity/lease sizing, worker authentication,
  cloud control/data permissions and paid-stage result/usage checkpoints.

## Local outbox reconciliation cases

These real-engine-backed synthetic setups retain the existing client/network
guards. Reconciliation never executes the job or engine approval/grading actions.
Only protected control/index/hash/snapshot/checkpoint metadata is inspected;
`CURRENT` is not a substitute for scoped byte validation or engine preflight.

- [x] `tests/test_outbox.py::test_current_pending_metadata_stays_eligible_without_execution_or_authority_changes`.
- [x] `tests/test_outbox.py::test_stale_pending_job_has_immutable_hold_surviving_restart`:
  removed from pending delivery without deleting intent/history; hold survives
  repository replacement and later Teacher cancellation preserves its audit.
- [x] `tests/test_outbox.py::test_poison_pending_control_records_are_quarantined_without_rewriting_evidence`:
  bad JSON/hash, rehashed paid stage/foreign binding, missing/invalid execution
  metadata and corrupt checkpoint are held without rewriting original evidence.
- [x] `tests/test_outbox.py::test_outbox_reconciliation_and_status_require_trusted_dispatcher`.
- [x] `tests/test_outbox.py::test_outbox_inspection_and_mutation_do_not_cross_tenants`.
- [x] `tests/test_outbox.py::test_outbox_page_limits_and_cursor_are_strict`.
- [x] `tests/test_outbox.py::test_cursor_progresses_past_unchanged_current_jobs_to_later_poison`.
- [x] `tests/test_outbox.py::test_reconciliation_rechecks_control_after_candidate_scan`:
  assignment/cancellation wins without a hold; changed inputs produce a stale hold.
- [x] `tests/test_outbox.py::test_transient_control_errors_are_not_terminal_quarantine`.
- [x] `tests/test_outbox.py::test_hold_insert_failure_rolls_back_without_changing_job_or_approval`.
- [x] `tests/test_outbox.py::test_concurrent_reconciliation_records_only_one_immutable_hold`.
- [x] `tests/test_outbox.py::test_rehashed_foreign_hold_cannot_replace_local_audit_scope`.
- [ ] Real transport poison messages, operator hold repair/release,
  queue delivery/consumer, worker identity and production permission separation.

## Bounded simulated delivery cases

The approved policy is three attempts total, then operator review, with waits
of 5 seconds and 30 seconds. Send claims reuse the five-minute server-owned
default, separately from engine execution. Only the fixed offline stage is
eligible. `SimulatedQueue` is intentionally an in-memory synthetic buffer;
durable SQLite control watermarks are not durable queue-message storage.
No background consumer/timer or real transport is enabled.

- [x] `tests/test_delivery.py::test_confirmed_simulated_delivery_is_durable_and_replay_does_not_resend`:
  preserved control records, same synthetic buffer, stable message/recipient,
  unchanged human authority and confirmed worker grant without executing validation.
- [x] `tests/test_delivery.py::test_retry_wait_is_server_owned_and_stable_nonce_does_not_increment`.
- [x] `tests/test_delivery.py::test_three_unconfirmed_attempts_stop_in_immutable_operator_review`.
- [x] `tests/test_delivery.py::test_duplicate_accepted_messages_share_one_job_and_reuse_validation_result`:
  lost acknowledgement produces duplicate buffered messages; actual pinned-engine
  validation runs once and the committed result is reused.
- [x] `tests/test_delivery.py::test_crash_watermark_survives_expiry_and_replacement`.
- [x] `tests/test_delivery.py::test_replaced_send_cannot_confirm_a_late_receipt`.
- [x] `tests/test_delivery.py::test_delivery_scope_cannot_cross_roles_or_tenants`.
- [x] `tests/test_delivery.py::test_retry_cannot_change_recipient_or_select_another_message`.
- [x] `tests/test_delivery.py::test_snapshot_change_or_cancellation_during_send_prevents_assignment`.
- [x] `tests/test_delivery.py::test_legacy_assignment_is_not_delivery_and_managed_assignment_cannot_bypass_send`.
- [x] `tests/test_delivery.py::test_already_assigned_legacy_job_is_not_automatically_sent`.
- [x] `tests/test_delivery.py::test_confirmation_and_assignment_rollback_together`.
- [x] `tests/test_delivery.py::test_concurrent_dispatchers_do_not_issue_two_live_sends`.
- [x] `tests/test_delivery.py::test_rehashed_delivery_stage_corruption_fails_closed`.
- [x] `tests/test_delivery.py::test_three_expired_unknown_send_attempts_cannot_issue_a_fourth`.
- [x] `tests/test_delivery.py::test_exhaustion_hold_failure_preserves_attempt_limit_and_recovers`.
- [x] `tests/test_delivery.py::test_expiry_at_confirmation_boundary_cannot_grant_worker_read_access`.
- [x] `tests/test_delivery.py::test_delivery_history_is_visible_only_to_its_tenant_dispatcher`.
- [ ] Durable queue storage, actual consumer delivery/visibility/poison handling,
  dispatcher service identity, operator hold-release policy and paid-stage retry rules.

## One-shot offline consumer and lifecycle cases

The coordinator uses the actual authenticated worker and protected receipt/
assignment; queue fields are untrusted routing hints, not execution authority.
Consumption is explicit and one-shot. Owner status/results are read-only and
do not issue a send, retry, approval or engine call. No HTTP worker route,
background queue loop or real transport is added.

- [x] `tests/test_coordinator.py::test_real_confirmed_queue_consumption_and_owner_lifecycle_reuse_result`:
  with/without attendance, actual pinned-engine validation, pending/ready/running/
  validated states, duplicate reuse, unchanged human history and private cleanup.
- [x] `tests/test_coordinator.py::test_queue_envelope_cannot_supply_stage_role_paths_or_execution_authority`.
- [x] `tests/test_coordinator.py::test_queue_consumption_requires_authenticated_assigned_worker`.
- [x] `tests/test_coordinator.py::test_opaque_message_ids_and_recipient_are_not_authority`.
- [x] `tests/test_coordinator.py::test_legacy_assignment_does_not_authorize_queue_consumption`.
- [x] `tests/test_coordinator.py::test_accepted_unconfirmed_message_is_not_consumer_authority`.
- [x] `tests/test_coordinator.py::test_lifecycle_and_historical_result_inspection_are_owner_teacher_scoped`.
- [x] `tests/test_coordinator.py::test_owner_lifecycle_tracks_live_and_expired_claims_without_starting_work`.
- [x] `tests/test_coordinator.py::test_cancelled_or_stale_job_is_inspectable_but_cannot_be_consumed`.
- [x] `tests/test_coordinator.py::test_old_validation_result_is_explicitly_historical_after_input_changes`.
- [x] `tests/test_coordinator.py::test_owner_lifecycle_exposes_exhausted_delivery_hold_without_auto_release`.
- [x] `tests/test_coordinator.py::test_owner_lifecycle_rechecks_version_after_snapshot_inspection`.
- [x] `tests/test_coordinator.py::test_corrupt_committed_result_cannot_be_reported_as_success`.
- [x] `tests/test_coordinator.py::test_consumer_cannot_bypass_another_live_execution_claim`.
- [x] `tests/test_coordinator.py::test_owner_can_inspect_expired_unknown_send_without_triggering_a_retry`.
- [x] `tests/test_coordinator.py::test_consumer_validates_protected_delivery_record_not_just_envelope`.
- [x] Owner HTTP job integration; verified cases below.
- [ ] Real queue durable acknowledgement/visibility recovery, owner job UI,
  production worker service identity and all paid/grading workflows.

## Teacher offline job HTTP cases

- [x] `tests/test_job_api.py::test_teacher_http_job_setup_replay_discovery_and_inspection_do_not_execute`:
  checkpoint-only preparation response, private-directory cleanup, stable replay,
  bounded discovery, pending result conflict and unchanged human authority.
- [x] `tests/test_job_api.py::test_all_job_http_routes_remain_owner_teacher_scoped`.
- [x] `tests/test_job_api.py::test_offline_http_mutations_require_literal_confirmation`.
- [x] `tests/test_job_api.py::test_offline_http_mutations_require_current_quoted_etag`.
- [x] `tests/test_job_api.py::test_offline_http_bodies_cannot_select_stage_recipient_or_paths`.
- [x] `tests/test_job_api.py::test_stale_offline_job_can_be_cancelled_with_current_exam_etag`.
- [x] `tests/test_job_api.py::test_cancellation_rechecks_etag_inside_its_write_transaction`.
- [x] `tests/test_job_api.py::test_job_and_checkpoint_ids_do_not_cross_owned_exam_boundaries`.
- [x] `tests/test_job_api.py::test_owned_job_paging_and_query_validation`.
- [x] `tests/test_job_api.py::test_verified_and_historical_results_are_readable_without_http_execution`:
  actual internal simulated delivery and pinned-engine validation; HTTP only reads.
- [x] `tests/test_job_api.py::test_owner_job_routes_recover_after_api_repository_replacement`.
- [x] `tests/test_job_api.py::test_no_worker_execution_or_paid_http_routes_were_added`.
- [x] Live HTTP smoke with `--regions --offline-jobs` and
  `--attendance --regions --offline-jobs`, synthetic only; flag requires regions.
- [ ] Browser job UX, real queue/worker identity, production quotas/retention/
  parser isolation, paid admission and deployed acceptance.
