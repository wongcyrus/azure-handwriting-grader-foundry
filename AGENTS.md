# Continuing this repository

Read `README.md`, `docs/implementation-plan.md` and `docs/test-checklist.md`
before changing code. The checklist is the durable implementation/test handoff;
the previous agent's chat or session todo database is not required.

## Boundaries

- This is the separate Foundry application, not the reusable engine repository.
- Consume the engine at the exact reviewed Git pin in `pyproject.toml` and
  `preflight.py`; never copy its grading logic or silently track `main`.
- Keep changes compatible with existing local grader/skill users.
- Do not commit or push implementation/checklist changes until the user reviews
  and explicitly approves them. Public `main` now contains the application
  through `9316676`, with successful hosted offline CI. Fenced offline execution
  is committed locally as `8152657`, not pushed. Outbox reconciliation is
  committed locally as `9631574`, also not pushed. Simulated delivery is committed
  locally as `cd6795f`, also not pushed. Consumer/lifecycle is committed locally
  as `48f3336`, not pushed. Teacher job HTTP is committed locally as `1411719`,
  not pushed. New teacher job UI changes still need separate
  review/commit/publication approval.
- No Azure deployment, paid inference, real student data or email without the
  relevant explicit approvals.
- Local development is localhost-only and synthetic-data-only. SQLite is not the
  production storage/authorization architecture.
- Teacher approval is not a model tool. Do not remove ownership, ETag, artifact
  hashes, engine provenance or validation gates to make tests pass.
- Do not replace real engine integration tests with fake validators. Core tests
  intentionally isolate state/auth; engine-marked tests exercise the pinned engine.
- Region previews use the first present script as the common-layout template,
  not a verified view of every student's scan. Use 200-DPI rendered pixel
  coordinates; retain PDFium's per-process serialization and pixel admission caps.
- `apps/web` is the React/TypeScript local canvas. Its development proxy is
  localhost-only. Synthetic tokens live in memory, never URL/storage; production
  identity setup is pending. Browser tests use real synthetic API/renderer flows.
- Offline CI runs only synthetic validation. Never add Azure credentials, real
  student data or deployment steps to that workflow without separate approval.
- `WorkspaceBridge` is an internal offline review-workspace adapter. Hydration
  and recovery require the current owner's authenticated Teacher principal and
  current input/region attestations (plus explicit CSV attendance attestation).
  Use a server-controlled private root, not caller-supplied paths. Default
  hydration never creates engine approvals. Explicit `prepare_engine_inputs`
  projects current API attestations into pinned engine files without calling
  engine approval actions, changing identities/times or granting job authority.
  Recovery preserves checkpoint kind; never upgrade a review implicitly.
  Local approval projections are not cloud authority. Model config and paid
  execution remain disabled.
  Preserve the checkpoint write transaction's version check and artifact hashes.
- `OfflineJobControl` admits only explicitly confirmed `validate_engine_inputs`
  intents from current owner-approved mapped checkpoints. Intent and outbox
  commit atomically; request/message identities are stable on replay. Only a
  trusted `JobDispatcher` can acknowledge delivery and assign a same-tenant
  `StageWorker` read grant. Worker reads are scoped to the job/message/assignment,
  current snapshot and allowed artifact hashes. These internal roles are not
  new HTTP authentication or unrestricted execution permissions.
- `OfflineValidationExecutor` runs only the fixed read-only input-validation
  stage. Five-minute server-clock claims use per-attempt UUIDs and monotonic
  fencing; live duplicates cannot start a second execution. Expiry allows a
  replacement attempt on its next delivery/call, not forced process termination
  or automatic queue scheduling. Late/cancelled/stale attempts cannot publish.
  Teacher cancellation must work even after input changes. Results are immutable,
  hash-checked and atomically committed with completion under the current exam
  version and claim. A known completed result is reused, never overwritten.
  Hydrate only hash-checked scoped job artifacts in a server-controlled private
  workspace; do not forge Teacher authority or call engine approval/grading
  actions. No queue client, worker HTTP authentication, model configuration or
  paid-stage admission is implemented.
- `OutboxReconciler` is pending-only local control metadata inspection, not a
  queue consumer or executor. Require a trusted `JobDispatcher`, protected
  tenant indexes, strict limits and opaque cursor paging. Recheck candidates
  under `BEGIN IMMEDIATE`; skip assigned/cancelled entries. Preserve immutable
  intent and human authority. Record hashed immutable stale/invalid holds;
  propagate unknown transient errors, never classify them as terminal poison.
  Normal pending delivery excludes holds and assignment rechecks them.
  `CURRENT` is metadata consistency, not full artifact/engine validation.
  No automatic hold release, retry scheduler or real transport is implemented.
- `OfflineDispatcher` implements only the synthetic queue contract. The approved
  policy is three total attempts with 5-second then 30-second waits; no automatic
  fourth attempt or paid-call retry. Persist send watermarks before side effects,
  preserve stable job/message/recipient identity and per-attempt fencing.
  Confirm enqueue and assignment atomically under current snapshot/claim checks.
  Unknown send outcomes may duplicate messages but cannot invent confirmation;
  terminal exhaustion creates an immutable `DELIVERY_REVIEW` hold.
  Never bypass managed delivery through the legacy acknowledgement API.
  `SimulatedQueue` is not durable storage. No background consumer, scheduler, real queue
  client, production dispatcher identity or new HTTP permission is implemented.
- `OfflineJobCoordinator` is one-shot internal consumption, not a background
  queue/ack loop. Require a strict opaque envelope, the actual authenticated
  assigned `StageWorker`, current approved scope and protected confirmed
  delivery; no legacy assignment or body-selected authority is sufficient.
  Do not forge Teacher/Dispatcher principals to read or hydrate worker state.
  Owner-only lifecycle/result inspection never starts work or approves inputs.
  Recheck the observed exam version and validate result hashes before showing
  success; distinguish historical validation after edits from current authority.
  Preserve separate send/execution fencing and immutable result reuse.
- Teacher HTTP job actions require current owner/tenant Teacher authority.
  Preparation/admission/cancellation need literal confirmation and quoted exam
  ETags; cancellation rechecks the current version inside its transaction even
  for stale jobs. Listing is bounded and index-scoped; GETs never dispatch,
  consume or approve. Historical results are evidence, not current authority.
  App startup initializes internal job tables/components without starting work.
  Keep roots server-controlled; preparation removes only its newly created
  private directory after checkpoint persistence. Do not expose worker execution
  or body-selected stage/recipient/path authority through these routes.
- `OfflineJobs` is the synthetic teacher browser panel, not an execution client.
  Explicit consent, saved approvals and no unsaved edits precede preparation/
  admission. Preserve the same checkpoint/request UUID after an unknown job
  response; no automatic retry/polling. Reads never adopt over local edits.
  Version conflicts require explicit reload; discarding edits and cancellation
  require confirmation. Keep historical summaries distinct from current
  authority/awarded scores. Namespace component keys so input and job panels
  cannot share identity across exam/version changes. Tokens remain memory-only.

## Validation and handoff

Use the commands and named cases in `docs/test-checklist.md`. Run tests covering
your changes plus existing required regression checks. Never claim engine tests
passed if they were skipped.

After changes, update the checklist with:

1. What is implemented and what remains incomplete.
2. Exact commands actually run, results/counts and verification date.
3. New/changed test selectors and remaining failure cases.
4. Required environment/dependency pins and blockers.
5. The next bounded task and acceptance criteria.

Tick cases only after verification. Proposed cloud features and deployment tests
remain unchecked until implemented and actually tested. Do not equate an approval
attestation with permission to grade, or local JWT tests with live Entra deployment.

Pending increments may include untracked files. Check `git status --short`;
an empty `git diff` does not mean there is no pending code.
