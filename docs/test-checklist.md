# Implementation and test handoff

This file is the persistent checklist for any agent continuing this application.
Read it with [the full plan](implementation-plan.md), [README](../README.md) and
[agent instructions](../AGENTS.md). Update it after each verified increment.

## Current checkout and publication

- Repository: `wongcyrus/azure-handwriting-grader-foundry`.
- Published baseline: `a662755538d079f896a7ee5a6306a3c84f4c6a12`, docs-only.
- Implementation and this checklist are local/uncommitted pending user review.
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
| Attendance | All roster students expected; absent-student workflow is not implemented |
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
```

Focused selectors:

```sh
uv run --frozen --extra dev --extra engine pytest tests/test_preflight_gates.py tests/test_engine_preflight.py
uv run --frozen --extra dev --extra engine pytest -m engine
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

Current preflight increment verified at **2026-11-24T15:00:39Z**:

| Check actually run | Result |
|---|---|
| Full application pytest suite with `dev` + `engine` extras | 73 passed, no skips; 53 core and 20 real-engine cases |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 20 Python files |
| `python tools/smoke_review.py` | Passed; live HTTP with real synthetic PDF/XLSX and clean shutdown |
| Documentation links/fences and test selectors | Passed; 35 executable selectors |
| `git diff --check` | Passed |

Raw JUnit report: ignored `.local/test-results/pytest.xml`. No inference, Azure
deployment or live Entra authentication was tested. Files remain uncommitted.

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
- [ ] Explicit attendance/presence review; absent students never inferred from scans.
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
2. Do not treat untracked implementation as already published.
3. Next bounded task: explicit optional attendance input and review. Preserve the
  full XLSX roster; validate CSV `ID,STATUS` using existing engine attendance rules;
  require explicit present/absent decisions, bind them to the snapshot and check
  PDF counts against present students. Never infer absence from missing scans.
4. Acceptance: missing/duplicate/unknown attendance IDs, omitted rows, invalid
  status and stale attendance review fail closed; absent students are not marked
  zero; all-roster default remains explicitly represented. No grading or paid call.
5. Then implement page rendering/region review with canonical coordinates and
  existing validators; keep the engine's scan checks before later grading.
6. Add focused positive/negative integration tests and a reproducible smoke path.
7. Update this checklist with observed results and remaining gates.

Cloud resources, paid tests, real student evaluation, commits and publication
remain separate user decisions. M0 school/region/privacy/budget decisions are not
resolved merely because local tests pass.
