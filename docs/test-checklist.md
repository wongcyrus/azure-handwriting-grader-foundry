# Implementation and test handoff

This file is the persistent checklist for any agent continuing this application.
Read it with [the full plan](implementation-plan.md), [README](../README.md) and
[agent instructions](../AGENTS.md). Update it after each verified increment.

## Current checkout and publication

- Repository: `wongcyrus/azure-handwriting-grader-foundry`.
- Published baseline: `a662755538d079f896a7ee5a6306a3c84f4c6a12`, docs-only.
- Verified foundation committed locally as `e8ad9cf` after explicit user approval;
  it has not been pushed. The new attendance increment is uncommitted.
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
| State/storage | SQLite local reference, optimistic ETags, retained artifacts and history |
| Human inputs | Explicit scan order/common layout, snapshot-bound teacher attestation |
| Engine bridge | Offline XLSX/PDF/roster/rubric preflight; provenance/integrity and revalidation |
| Attendance | Optional complete CSV; present/absent preview and distinct teacher attestation; web UI pending |
| Production Blob/Queue, budgets/jobs | Not implemented |
| Skills/Foundry protocol/hosting | Not implemented |
| Teacher browser UI/score review | Not implemented |
| Terraform/CI/cloud deployment | Not implemented |
| Grading/reports/delivery | Not implemented; no paid or grading endpoint |

Input review does not authorize grading. PDF counts do not prove correct scan
order/identity. No orientation/alignment/rendering check is implemented in this
API yet; preserve the engine's downstream checks when integrating grading.

## Reproducible validation commands

Run from the application root:

```sh
uv sync --extra dev --extra engine
uv run --frozen --extra dev --extra engine pytest
uv run --frozen --extra dev --extra engine ruff check .
uv run --frozen --extra dev --extra engine ruff format --check .
uv run --frozen --extra dev --extra engine python tools/smoke_review.py
uv run --frozen --extra dev --extra engine python tools/smoke_review.py --attendance
```

Focused selectors:

```sh
uv run --frozen --extra dev --extra engine pytest tests/test_preflight_gates.py tests/test_engine_preflight.py
uv run --frozen --extra dev --extra engine pytest -m engine
uv run --frozen --extra dev --extra engine pytest tests/test_attendance.py
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

Attendance increment verified at **2026-11-24T15:20:24Z**:

| Check actually run | Result |
|---|---|
| `pytest tests/test_attendance.py tests/test_engine_preflight.py` | Initial focused run: 41 passed; additional edge cases included in full run below |
| Full application pytest suite with `dev` + `engine` extras and JUnit | 101 passed, no skips/failures/errors; 53 core and 48 real-engine cases |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 21 Python files |
| `python tools/smoke_review.py` | Passed; live HTTP with real synthetic PDF/XLSX and clean shutdown |
| `python tools/smoke_review.py --attendance` | Passed; explicit present/absent preview, present-only PDF count and two teacher attestations |
| Documentation links/fences and test selectors | Passed; 47 executable selectors |
| `git diff --check` | Passed |

Raw JUnit report: ignored `.local/test-results/pytest.xml`. No inference, Azure
deployment or live Entra authentication was tested.

Attendance remains uncommitted pending review. Both smoke commands clean up their
own localhost server and temporary files. No Azure resources were deployed.

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
- [ ] Full-page rendering/orientation/sequence and box validation in cloud review.
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
3. Next bounded task: offline rendered page previews
  and manual region review. Use the pinned renderer and existing region validators;
  store page dimensions/provenance and canonical coordinates.
4. Acceptance: unauthorized/stale edits, invalid page/question IDs, out-of-bounds
  boxes and changed scans/rubric invalidate the relevant review. Test zoom/DPR
  conversions when adding UI. No suggestion model or paid call is needed.
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
