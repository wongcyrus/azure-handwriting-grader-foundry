# Implementation and test handoff

This file is the persistent checklist for any agent continuing this application.
Read it with [the full plan](implementation-plan.md), [README](../README.md) and
[agent instructions](../AGENTS.md). Update it after each verified increment.

## Current checkout and publication

- Repository: `wongcyrus/azure-handwriting-grader-foundry`.
- Published baseline: `a662755538d079f896a7ee5a6306a3c84f4c6a12`, docs-only.
- Verified foundation committed locally as `e8ad9cf` after explicit user approval;
  attendance committed as `708cff1` after explicit approval. Neither is pushed.
  Region review `9d05ab0` and canvas `9f8e2f0` are also unpushed.
  Owned-exam selection is committed as `184875d`, also unpushed. The user has
  authorized committing verified input setup/review, now `bff8e5b` (unpushed).
  Offline CI is committed as `7eb4ed8` after explicit approval, also unpushed.
  Browser input-edge regressions are committed as `66bc1eb` after explicit
  approval, also unpushed. Offline review-workspace hydration is committed as
  `0af4d51` after explicit approval, also unpushed. Explicit engine input
  approval mapping is committed as `ed07852`, also unpushed. Offline validation
  job control and this handoff are uncommitted pending review;
  publication is not authorized.
- A fresh GitHub clone does not yet contain the application. Another agent must
  use this worktree until publication is explicitly approved.
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
| Offline validation intents/outbox | Explicit confirmed owner requests, immutable idempotent intent + atomic outbox, trusted dispatcher assignment and scoped worker reads; no executor/queue or paid stage |
| Attendance | Optional complete CSV upload, status preview and independent teacher attestation; production acceptance pending |
| Region review | First-present-script JPEG template, actual pixel dimensions, validated drafts and separate geometry attestation |
| Local teacher canvas | React/TypeScript pointer/keyboard editing, CSS/zoom/DPR conversion, page review, approval and explicit conflict recovery |
| Production Blob/Queue, budgets/job execution | Not implemented |
| Skills/Foundry protocol/hosting | Not implemented |
| Teacher setup/input review | Local creation, raw uploads, layout settings, full roster/rubric/status preview and explicit input/attendance approval |
| Score UI and production login | Not implemented; all browser flows remain synthetic localhost only |
| Offline CI | Pinned-action workflow linted; equivalent local commands passed; GitHub-hosted execution unverified |
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
- [ ] Fenced execution, incremental engine checkpoints and unknown provider outcomes.
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
3. Next bounded task: add fenced, expiring claims and cancellation for the fixed
  offline validation stage, then a read-only validator/result boundary. Duplicate
  deliveries or concurrent processes sharing an identity must not execute twice;
  expired/cancelled/stale workers must not publish. Do not connect real queues,
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
- [ ] Fenced/expiring execution claims, cancellation, stale-outbox reconciliation,
  poison handling, executor result persistence and real queue delivery.
- [ ] Production worker authentication and separate control/artifact permissions,
  cloud job APIs/UI, approved paid budgets/stages and Foundry runtime execution.
