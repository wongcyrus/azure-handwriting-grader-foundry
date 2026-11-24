# Foundry-hosted teacher application: full implementation plan

**Status:** Proposed implementation; nothing in this document is deployed.
**Evidence reviewed:** 2026-11-24.
**Target:** `wongcyrus/azure-handwriting-grader-foundry`, the separate teacher application.
**Engine dependency:** `wongcyrus/azure-handwriting-grader-skills`, pinned to
`3b155f9232cb0730587d89677c932ea049dd7f71`; do not copy or fork its implementation.

Implementation has started with the limited local review API described in the
[application README](../README.md). The rest of this document describes the target
system, not completed functionality.

This plan adds a teacher-facing web application and a skill-driven Microsoft
Agent Framework agent hosted in Microsoft Foundry. It preserves the existing
Python grading engine, reviewed-input checks, pricing verification, human score
approval and separate delivery approval.

The plan is not permission to create resources, upload student data, perform paid
inference, change production settings or commit implementation changes. Each
requires the applicable review and explicit authorization.

## 1. Outcome and scope

### First production pilot

An authorized teacher can:

1. Sign in with the school's Microsoft Entra identity.
2. Create an exam through a wizard, without editing YAML or running commands.
3. Upload scans, a roster and a rubric; explicitly identify present/absent students.
4. Review scan order, identities, rubric criteria and answer bounding boxes.
5. Approve displayed costs before each paid stage.
6. Submit grading as a recoverable background job.
7. Review every identity and mark, correcting flagged/failed items.
8. Approve results and download reports.
9. Return later or use another browser without losing review progress.

The optional conversational agent guides the same workflow using real runtime
skills. It cannot bypass the wizard's authorization, approval or cost checks.

### Initial defaults, subject to school approval

| Decision | Proposed pilot default |
|---|---|
| Tenancy | One school/Entra tenant per deployment |
| Roles | Teacher and school administrator; no public registration |
| Exam access | Owner only, with explicit co-teacher grants if implemented |
| Browser application | React/TypeScript on Static Web Apps Standard |
| API | Python Azure Functions, Consumption plan |
| Long-running execution | Foundry-hosted Python container |
| Durable data | Private Blob Storage; Storage Queue for dispatch |
| Agent protocol | Responses 2.0.0 with explicitly enabled resilient background execution |
| Agent skills | Trusted, image-bundled skills through Framework `SkillsProvider` |
| Model provider | Azure OpenAI only; no public OpenAI or Gemini fallback |
| AI assistance | Opt-in conversational assistance with a displayed spending allowance |
| Initial outputs | Approved score exports, local statistics and existing supported reports |
| Optional paid outputs | Separately approved analysis and infographics |
| Delivery | Downloads only initially; email and Teams are later extensions |
| Review lifetime | School-defined retention, independent of Foundry session retention |

Do not treat these defaults as resolved procurement, privacy or deployment
decisions. Region, language coverage, workload limits, school policy and budgets
must be agreed at milestone M0.

### Deferred scope

Multi-school SaaS onboarding/billing, automatic email, Teams/Copilot publication,
LMS integration, public signup, student accounts, arbitrary uploaded skills,
unrestricted shell execution, individual-student paid regrading and automatic
absence inference are not pilot requirements.

Existing locally supported capabilities remain available to existing CLI/skill
users. Cloud work must not silently alter their dependencies or behavior.

## 2. Verified starting point

| Existing component | Reuse | Required cloud work |
|---|---|---|
| [Workflow][engine-workflow] | Approval validation, threaded synchronous grading, draft output | Request-scoped factory and async integration; add conversational skills separately |
| [Grading engine][engine-grading] | Approved inputs, scan validation, batching, ledgers, resume/retry | Durable artifact bridge, scoped workspaces, cancellation/recovery integration |
| [Attendance][engine-attendance] | Explicit present/absent validation and approvals | Wizard/editor and authenticated cloud approval |
| [Rubric][engine-rubric] | Import/extraction, criteria validation and approval | Browser editing and versioned artifacts |
| [Regions][engine-regions] | Geometry validation and approval binding | Cloud review API and canvas |
| [Region editor][engine-editor] | Interaction patterns and validation behavior | Replace localhost HTTP/token transport |
| [Score editor][engine-score-editor] | Blind marking, crop inspection, grouping, corrections | Replace process-global caches and local review transport |
| [Grade approval][engine-grade-review] | Full review validation and hash-bound approvals | Authenticated teacher provenance and protected authoritative state |
| [Run context][engine-run-context] | Isolated child runs | Preserve run semantics in durable storage |
| [Pricing][engine-pricing] and [telemetry][engine-telemetry] | Fail-closed rates and recorded estimates | School configuration, stage budgets and cloud accounting |
| [Public skill][engine-skill] | Domain workflow and safety rules | Cloud-native runtime skill with typed tools, not CLI instructions |

Important current constraints:

- The existing workflow does not load `SKILL.md` or construct a conversational
  agent. Adding a `SkillsProvider` is implementation work, not an existing feature.
- `RequireHumanReview` yields the draft path; it does not suspend for approval or
  confer approval.
- The synchronous wrapper uses `asyncio.run`. Inside the hosted async server use
  the async workflow API, not that wrapper.
- `grade_exam` independently validates scan orientation/sequence before grading.
  Preserve this check; do not rely only on a previous browser preflight.
- Local review servers bind to `127.0.0.1` and have process-local state. Making
  them publicly reachable is not the cloud migration strategy.
- Local hashes detect changed artifacts but are not authenticated teacher
  identity or a tamper-proof audit system.
- Existing resume/retry behavior does not guarantee exactly-once provider billing.

## 3. Target architecture

```text
Teacher browser + Entra sign-in
                |
Static Web Apps Standard
  wizard / optional chat / crop canvas / marking grid / downloads
                |
Azure Functions API
  exam authorization / version checks / approvals / budgets
      |                    |
      |                    +--> protected control state + pending-job outbox
      |
      +--> short-lived, object-scoped upload/download authorization
      |                         |
      |                    private Blob Storage
      |
      +--> Storage Queue --> short-lived dispatcher
                                      |
                          Foundry stored background request
                                      |
                          Python hosted agent container
                            Responses adapter
                            Agent Framework + runtime skills
                            allowlisted Python tools
                            existing grading/reporting engine
                                |                 |
                         scoped artifacts     Azure OpenAI
                                |
                     completion/progress reconciliation
                                |
                     API-owned exam state and review screens

Deployment: CI build --> ACR image digest --> Terraform hosted-agent definition
Operations: redacted metrics/traces --> Application Insights
```

### Ownership and trust boundaries

| Actor | Allowed actions | Not allowed |
|---|---|---|
| Teacher | Review owned/granted exams; submit explicit approval actions | Access another teacher's exam or directly modify control storage |
| Administrator | Manage school access, approved models/rates/budgets and retention | Impersonate teacher review without an explicit audited policy |
| API/control functions | Authorize actions; write authoritative exam state and approvals | Accept caller-supplied identity as proof of approval |
| Dispatcher | Submit a valid pending job; reconcile execution state | Manufacture human approval or change reviewed inputs |
| Hosted runtime | Read approved job context; execute permitted stages; publish artifacts/progress | Write authoritative human approvals or select arbitrary student-data paths |
| CI deployment identity | Deploy reviewed infrastructure and immutable releases | Read student artifacts by default |

Separate API-owned control/approval containers from worker-writable artifact
containers. The runtime receives only read access to the approval context it
needs; it must not have storage permissions to forge authoritative approval state.
Container prefixes alone do not enforce teacher ownership: every API and tool
operation checks school, exam, revision and authenticated caller/job scope.

The Foundry project/image-pull identity and runtime agent identity have different
purposes. Configure and test their permissions independently.

## 4. Data model, versioning and storage

Use opaque server-generated identifiers for school, exam, revision, job and
artifact. Never use a teacher-supplied filename as a storage path.

### Core records

| Record | Minimum content |
|---|---|
| Exam | Schema version, school, owner/grants, title, current revision, state, retention policy |
| Revision | Parent, immutable input references/hashes, settings, rubric/regions/review versions, model/config versions |
| Artifact | Kind, immutable blob/version reference, SHA-256, content type, size, provenance |
| Approval | Kind/stage, teacher identity, UTC time, reviewed snapshot/hash, scope, current quote/budget where applicable |
| Job | Stable ID, revision/stage, approved snapshot, release/model version, state, attempt/input identity, checkpoints |
| Budget ledger | Approved allowance, reservations, recorded usage, unknown outcomes and reconciliation status |
| Review event | Actor, artifact version, changed fields/rows, previous/new values, reason where required, UTC time |

Audit records contain protected personal information and need school-defined
access/retention. Do not send review values, student identities or full model
prompts to ordinary operational logs.

### Storage design

```text
control/       API-owned exam manifests, approvals, budget reservations, outbox
uploads/       quarantined original files awaiting verified finalization
artifacts/     immutable inputs, pages, crops, rubric/review versions and reports
execution/     job checkpoints, per-call watermarks and progress proposals
tfstate/       separate restricted infrastructure state; never application data
```

Names above are logical containers/categories, not a deployment already created.
Keep Terraform state in a separately permissioned account/container.

Use a single authoritative exam-state manifest with conditional ETag writes for
each atomic state transition. Write immutable artifacts first, then conditionally
publish their references. Unreferenced uploads are not approved inputs and can be
cleaned according to a bounded quarantine policy.

An approval plus its pending-job entry must commit in the same state mutation.
A dispatcher/reconciler retries delivery to the queue; it must not lose a job if
the process stops after approval but before queue submission. Queue delivery is
at least once, so consumers must check the stable job identity.

Worker progress is a proposal in execution storage or an authenticated worker
callback. A control function validates job identity, state and fencing before
updating the authoritative exam manifest.

Retain previous revisions and review snapshots. ETags prevent lost updates but
are not audit tamper protection. Evaluate additional immutability controls against
the school's retention/erasure obligations instead of promising indefinite WORM
storage by default.

### Compatibility with the filesystem-based engine

Create an artifact/workspace adapter, not a replacement grading algorithm:

1. Hydrate the exact approved input versions into a scoped workspace.
2. Generate server-controlled exam/model configuration from approved settings.
3. Preserve file bytes and stable paths required by current manifests and hashes.
4. Materialize local approval files only from authoritative cloud approvals.
5. Invoke current Python validators and stage functions.
6. Publish immutable outputs and durable checkpoint references.
7. Validate provenance again before publishing a review-ready revision.

Recovery must restore a compatible workspace, including referenced paths,
configuration bytes and manifests. Merely changing `output_dir` or copying
approval files into a new run is insufficient.

Foundry session files are useful working storage but not the school's archive.
Publish progress at tested engine checkpoint/side-effect boundaries, not just
once at the end. Introduce narrow optional persistence hooks where needed while
preserving existing local behavior.

## 5. Human-in-the-loop state machine

Track exam/revision state separately from job state. Human review is a durable
application state, not a long-running model request.

### Normal revision flow

```text
SETUP
  -> INPUTS_VALIDATED
  -> PREPARATION
  -> WAITING_FOR_INPUT_REVIEW
  -> WAITING_FOR_GRADING_COST_APPROVAL
  -> GRADING_QUEUED
  -> GRADING_RUNNING
  -> WAITING_FOR_SCORE_REVIEW
  -> SCORES_APPROVED
  -> REPORTS_QUEUED
  -> REPORTS_READY
```

Optional paid preparation, analysis, embeddings and images each use a
`WAITING_FOR_COST_APPROVAL(stage)` substate before job submission. Local import,
manual box editing and local grouping do not require a model call, although
cloud compute/storage still have costs.

Optional future delivery follows:

```text
REPORTS_READY -> DELIVERY_PREVIEW -> WAITING_FOR_DELIVERY_APPROVAL -> DELIVERY
```

Job states include `PENDING_DISPATCH`, `QUEUED`, `RUNNING`,
`RECOVERY_PENDING`, `AWAITING_OPERATOR_DECISION`, `SUCCEEDED`, `FAILED`,
`CANCEL_REQUESTED` and `CANCELLED`. Each transition has a server-enforced
precondition; arbitrary status updates from the browser or LLM are rejected.

### Review gates

| Gate | Required human decision | Server validation |
|---|---|---|
| Attendance | Explicit presence/absence and scan mapping | Complete roster coverage; unique IDs; preserve leading zeros; present count matches layout |
| Rubric | Criteria, question identifiers and maximum marks | Existing rubric rules; current artifact and source/config hashes |
| Regions | Page/question boxes, scan order and layout | Bounds and expected questions; canonical rendered-page coordinates |
| Paid stage | Exact stage, affected data and displayed cost | Current pricing/config; approved snapshot; workload and allowance |
| Identity/score review | Every script and mark reviewed | Full coverage; valid unique present IDs; finite in-range marks |
| Flagged/failed/corrected answers | Explicit manual decision | Existing manual-mark requirements; no silent default to zero |
| Analysis, if enabled | Review generated teaching recommendations | Analysis/review provenance before advanced reports |
| Delivery, if enabled | Recipients and attachments | Current approved reports and independent delivery approval |

Frontend validation improves usability but never replaces backend validation.
Review attestations record teacher actions, not proof that a person examined
every pixel.

### Approval transaction

1. Authenticate the teacher and resolve current exam permissions.
2. Require the expected exam ETag and exact reviewed artifact versions.
3. Run domain validation over the immutable snapshot.
4. Capture identity from validated authentication, never from request fields.
5. Bind approval to all dependent inputs and applicable model/pricing scope.
6. Atomically commit approval, state transition and pending job if applicable.
7. Reject stale versions with a conflict response and a refresh/review action.
8. Recheck scope, provenance and authorization at job execution.

If cost or reviewed inputs change before dispatch, stop and request the relevant
new approval. Do not overwrite an approved revision. Targeted regrading follows
existing child-run rules, including regrading the selected question for all
present students; a crop preview is not itself a paid regrade.

## 6. Teacher web application

### Screens and behavior

| Screen | Implementation requirements |
|---|---|
| Home/exam list | Owned/granted exams, current stage, resume/review actions |
| Setup wizard | Roster, attendance, pages per student, scan order, rubric, reporting preferences |
| Upload/preflight | Per-file progress, limits, quarantine/validation status and actionable errors |
| Attendance/identity review | Preserve string IDs; separate absence from missing scans or failed OCR |
| Rubric editor | Question text, criteria, maximum marks, validation and versioned save |
| Region canvas | Rendered page, zoom, keyboard-accessible boxes, expected question labels and explicit approval |
| Stage cost preview | Models/region, transmitted data, estimated requests, allowance and current pricing provenance |
| Job status | Progress, recorded estimated cost, failures, cancellation and recovery decisions |
| Marking grid | Answer crop, rubric, transcription, suggested/manual mark, reasoning, flags and review status |
| Review history | Version comparison, attributable changes and stale-approval warnings |
| Results/downloads | Only valid approved exports; local statistics; optional paid-output menu |
| Administration | Access, approved deployments/rates, limits, budgets, retention and audit visibility |

### Browser/API details

- Use direct object-scoped uploads to private Blob Storage rather than buffering
  an entire class PDF through a Function/SWA request.
- Upload authorization is short-lived and write-only for one reserved object.
  Finalization verifies actual blob size/type/hash server-side before use.
- Bound file size, pages, rendered pixels, concurrency and decompression work.
  Reject malformed/unsupported inputs without starting paid inference.
- Convert canvas edits to the renderer's canonical page coordinates. Test zoom,
  display scaling, rotation handling and device pixel ratio explicitly.
- Save draft edits with optimistic concurrency. Preserve local unsaved edits on
  a conflict and show a merge/reload decision; never silently overwrite.
- Blind marking responses omit identity fields where feasible. Full-page views
  may reveal handwritten identities and must explain that limitation.
- Bulk review/edit actions require a current preview of the affected rows.
  Flagged/failed rows cannot be swept through approval without required decisions.
- Poll the application's persisted status, not the hosted-agent endpoint during
  human review. Chat streaming is optional and separate from durable job status.
- Support keyboard navigation, clear status labels and responsive layouts.
  Do not promise comfortable precision box editing on a small phone screen.
- Downloads require current exam authorization. Any delegated URL is short-lived,
  object-scoped and excluded from logs/referrers.

No browser receives Azure model credentials or arbitrary filesystem paths.

## 7. API and service contracts

Proposed routes; final schemas/OpenAPI are deliverables of M2.

| Method/route | Purpose | Required protection |
|---|---|---|
| `POST /api/exams` | Create an exam | Teacher role; school quotas |
| `GET /api/exams/{exam}` | State and permitted next actions | Exam permission; no cross-exam references |
| `POST /api/exams/{exam}/uploads` | Reserve bounded upload | Allowed type/size and scoped authorization |
| `POST /api/exams/{exam}/uploads/{upload}/finalize` | Verify uploaded object | Reserved object/version; idempotent finalization |
| `POST /api/exams/{exam}/revisions` | New immutable working revision | Parent permission/version |
| `PATCH /api/exams/{exam}/revisions/{revision}/review` | Save reviewed values | ETag, typed validation and attributable changes |
| `POST /api/exams/{exam}/revisions/{revision}/cost-previews` | Produce stage quote | Current settings/rates; no inference |
| `POST /api/exams/{exam}/revisions/{revision}/approvals` | Teacher approval | Teacher authentication, exact snapshot, ETag |
| `GET /api/jobs/{job}` | Persisted status | Owning exam permission |
| `POST /api/jobs/{job}/cancel` | Cooperative cancellation | Permission; idempotency |
| `POST /api/jobs/{job}/recovery-decisions` | Approved recovery/retry | Explicit scope/cost; unknown-outcome handling |
| `GET /api/exams/{exam}/artifacts/{artifact}` | Review/download access | Artifact belongs to permitted exam/revision |
| `POST /api/exams/{exam}/assistant` | Optional skill-guided chat | Exam permission and accepted chat allowance |
| Internal budget/progress routes | Worker reservations/completion | Worker identity, job scope, fencing; never teacher approval |

Use a consistent error envelope with a non-sensitive correlation ID and an
actionable code such as `STALE_REVIEW`, `APPROVAL_REQUIRED`, `PRICING_CHANGED`,
`INVALID_LAYOUT`, `BUDGET_LIMIT` or `UNKNOWN_PROVIDER_OUTCOME`.

Browser caller identities and worker identities have distinct authorization
paths. If SWA provides a trusted principal header, accept it only through the
verified hosting boundary; do not trust the same header from a directly reachable
backend. If using bearer tokens, validate issuer, audience, tenant and role.
Cookie-authenticated mutations require CSRF protection.

Idempotency keys are scoped to caller, exam, revision, stage and request digest.
Reusing a key with different content is a conflict, not permission to rerun.

## 8. Skill-driven agent and hosted runtime

### Runtime design

Use the existing Framework graph for grading inside a new request-scoped hosted
application. Construct fresh agent/tool context for each authorized request or
job. Do not share mutable teacher state or score caches between requests.

Implement Foundry's runtime contract:

- Linux `amd64` container and compatible pinned dependencies.
- Port 8088; `GET /readiness`.
- Responses protocol endpoint with declared version 2.0.0.
- Platform environment handling and graceful `SIGTERM`.
- Background/resilience support through a reviewed compatible SDK adapter.

Prefer a stable protocol adapter around the Framework application if the native
Framework hosting package remains prerelease or incompatible. Evaluate
`azure-ai-agentserver-responses` and native Framework hosting in M0; pin the
chosen combination in a separate reviewed cloud lockfile. Do not blindly install
umbrella packages or unpinned `--pre` examples.

Existing Framework pins are not a permanent safety claim. Review current
advisories, transitive dependencies and compatibility before adopting new
packages. No package is selected merely because it is the newest.

### Runtime skills

Bundle a cloud-native derivative of the current domain skill in the immutable
agent image. It must explain wizard/review actions and typed tools, not instruct
the hosted runtime to install packages or run unrestricted CLI commands.

Use a plain Framework agent plus `SkillsProvider` with progressive disclosure.
Trusted skill references live beside the skill. Uploaded exams/rosters cannot
write to those directories or supply new skill metadata.

The baseline does not depend on Foundry's preview central Skills registry,
managed Copilot harness or a shell-enabled harness. No arbitrary script runner is
required: registered tools call vetted Python functions.

### Proposed tool surface

| Tool category | Examples | Enforcement |
|---|---|---|
| Read state | Current stage, missing decisions, job status | Authorized scoped context; minimum data |
| Prepare | Validate uploads, import rubric, prepare review pages | Input/resource limits; cost gate if AI is requested |
| Preview | Stage cost and affected artifacts | No implicit inference or approval |
| Request work | Submit already-approved grading/report stage | API checks current human approval and budget |
| Review navigation | Return permitted review-screen links | App-relative links; no access-token URLs |
| Recovery guidance | Explain failed/unknown work and available decisions | Never silently resubmit ambiguous paid work |

Do not register `approve_*`, `send_email`, arbitrary file reads, arbitrary HTTP
requests or shell execution as autonomous agent tools. Approval materialization
is a trusted service operation after verified human action, not an LLM decision.

The assistant first offers missing decisions in ordinary teacher language. When
human review is needed it links to the correct screen, rather than inventing a
review or asking the teacher to paste a command.

Wizard/manual review remains usable with AI assistance off. Starting chat is
itself paid model usage and requires the applicable displayed allowance/consent.

## 9. Background execution, checkpoints and recovery

### Dispatch protocol

1. Persist approval and `PENDING_DISPATCH` in the protected control record.
2. Deliver a small queue message containing stable job/input identifiers.
3. Dispatcher acquires a fenced dispatch lease and rechecks the approved snapshot.
4. Submit a stored Foundry background request with job-scoped context.
5. Persist the Foundry response/work identity without keeping a Function waiting
   for the entire grading run.
6. Worker hydrates approved inputs and resumes from validated checkpoints.
7. Publish outputs/checkpoints; control reconciliation advances review state.
8. Stop/suspend compute after the stage completes, not after teacher review.

A browser disconnect is not job cancellation. Cancellation is a separate
authenticated request with a visible outcome.

### Durable boundaries

Stored background requests alone do not provide crash recovery. Explicitly enable
resilient background execution in the chosen adapter. An outer hosted request
using `store=false` cannot support that stored recovery path. This is separate
from the existing inner Azure OpenAI calls using `store=False`.

Use stable work/input identities, fencing and durable checkpoints. Recovery
reenters the handler; it does not restore Python local variables or thread stacks.

Persist before/after side-effect watermarks at paid-call boundaries. On recovery:

| Evidence | Action |
|---|---|
| Completed result and matching durable checkpoint | Reuse it; do not reissue the call |
| Work not started; current approval/pricing remains valid | Continue within approved scope |
| In-flight watermark without trustworthy outcome | Mark unknown; require operator/teacher decision before possible rebilling |
| Changed input/model/config or expired pricing evidence | Stop for a new valid decision |
| Partial cohort/question | Preserve progress; resume using existing cohort/regrading rules |

At-least-once dispatch, resilient handler reentry and checkpointing do not make
Azure inference billing exactly once. Do not promise that an unknown provider
outcome can be recovered without a possible additional charge.

Use bounded queue retries and poison-message handling for transport failures.
Do not translate them into unlimited paid model retries. Review cloud SDK retry
settings explicitly and preserve existing local defaults unless separately
approved.

Cancellation stops new work cooperatively; an already-issued model call may
finish or be billed. A `SIGTERM` flushes durable progress or defers recovery,
rather than falsely declaring success/cancellation. A thread running synchronous
grading needs an explicit cooperative boundary; cancelling its async waiter alone
does not stop the thread.

## 10. Pricing, budgets and operating costs

### Cost governance

Administrators select permitted deployments, exact underlying models, region,
billing mode, configuration versions and pricing evidence. Teachers approve the
specific work and displayed allowance; rate verification does not grant consent.

Before each paid stage show:

- Stage purpose, affected students/questions and data sent.
- Deployment/model/region and current verified unit rates.
- Estimated requests and cost, including uncertainty and applicable output limits.
- Existing recorded usage, unknown outcomes and additional allowance needed.

Use decimal accounting and separate hosted compute, conversational model usage,
grading/analysis/image usage and shared platform costs.

Reserve a conservative per-request amount under conditional control-state writes
before issuing a call. Reconcile recorded usage afterwards. The allowance is an
application guard, not an exact invoice guarantee: token estimates, unknown
responses and provider billing can differ. Fail closed when a safe reservation
cannot be established or pricing changes.

Azure budget alerts are notifications, not instantaneous hard spending stops.
Add application concurrency/workload limits and an administrator switch disabling
new paid stages. A pause must not erase running-job history.

### Cost worksheet

Record selected resource meters and school assumptions before deployment:

| Category | Calculation |
|---|---|
| Hosted compute | Aggregate billable session-hours x allocated CPU/memory rate |
| Models | Recorded input/cached/output/image usage x verified applicable rates |
| Portal | Chosen Static Web Apps plan |
| Registry | Selected daily tier plus applicable storage/build/network usage |
| API/queues/storage/logging | Measured requests, compute, retained bytes and operations |
| Optional enterprise requirements | Private networking, upgraded registry, licensing and other selected services |

The earlier approximately USD 14-16 fixed baseline assumes one Standard portal,
Basic ACR and consumption-based backend without additional always-on services.
It is not an unavoidable minimum or a full school bill. Portal meter region and
Foundry region must be checked separately; not every service uses identical
region identifiers. Retained data/logs can cost money with no grading activity.

The illustrative Southeast Asia hosted rate reviewed on 2026-11-24 was
USD 0.11928/vCPU-hour plus USD 0.01416/GiB-hour. At 2 vCPU/4 GiB that is
USD 0.2952 per billable session-hour, before all other charges. Allocation is
not yet benchmarked. Reverify rates and region availability before deployment.

The saved four-student example is historical evidence, not a normal-class quote.
Recorded estimates exclude some failed/retried requests. Display unknown cost
as unknown, not zero; Azure billing remains authoritative.

Start with a short configurable idle timeout, stop completed sessions, disable
unrequested images and cap logs. Validate cold-start/recovery behavior before
settling on the lowest supported timeout.

## 11. Terraform and release implementation

### Proposed layout

These are future additions, not files already implemented:

```text
apps/
  web/                         React/TypeScript application and own lockfile
  api/                         Functions app and separately pinned dependencies
  agent/                       Hosted entrypoint, Dockerfile, cloud lockfile
    skills/handwriting-grading/ Cloud-native runtime skill and references
src/
  handwriting_grader_cloud/     Context, schemas, artifact/state adapters, policies
infra/
  bootstrap/                   Protected remote state and CI federation
  platform/                    Shared Azure infrastructure
  agent/                       Logical hosted-agent data-plane deployment
  environments/                Nonsecret reviewed dev/pilot/prod inputs
tests/
  cloud/                       Domain/API/recovery integration tests
  e2e/                         Synthetic teacher browser journeys
```

This application is separately packaged. The engine is a pinned dependency.
Any narrow engine persistence hooks belong in its own repository and require
backward-compatibility testing. Neither cloud/browser/hosting dependencies nor
installation steps should become mandatory for existing grader users.

### Resource ownership

| Configuration | Responsibilities |
|---|---|
| Bootstrap | Restricted remote state, locking, CI federated identity |
| Platform | Resource group, Foundry account/project, approved model deployments, RAI policy, storage/queues, registry/connection, API/frontend hosting, RBAC, monitoring/budgets |
| Agent | Named agent definition through AzAPI data plane, digest, allocation, protocol, nonsecret configuration, full RAI policy ARM ID |
| CI/release | Build/publish code, capture release/version identity, readiness/functional checks and approved promotion |

Use AzureRM where supported and `azapi_data_plane_resource` with
`Microsoft.Foundry/agents@v1` for the logical hosted agent. Its parent is the
project data-plane endpoint, not the project ARM ID. Microsoft currently
documents AzAPI 2.9.0 or later; commit a reviewed provider lockfile.

Terraform manages the named agent, not an independently owned resource for every
version. Capture the candidate version from a serialized deployment, verify its
definition/digest, and keep production pinned until it passes checks. Do not
assume an unchanged apply creates a new release or that a concurrently queried
`latest` belongs to this deployment.

Use one deployment owner per agent; prohibit competing portal/SDK/CI writers.
Protect production resources from accidental destruction, with a separately
reviewed decommission process. Keep rollback images and compatible schema/code
versions until policy allows their removal.

### CI sequence

1. Run engine regressions and new cloud/API/browser tests against synthetic data.
2. Check dependencies/secrets and generate a release inventory/SBOM.
3. Run Terraform formatting/validation and produce a reviewed plan.
4. Obtain environment approval before infrastructure apply.
5. Build a `linux/amd64` image; push under a unique tag and resolve its digest.
6. Deploy frontend/API packages and candidate hosted-agent definition.
7. Configure/test image-pull, runtime data/model and API authorization roles.
8. Wait for the exact candidate to become active; verify digest/config.
9. Run authenticated synthetic checks and actual guardrail-effect tests under
   separately approved paid-test allowances where inference is needed.
10. Promote the approved candidate; retain a tested rollback target.

An active agent is not proof a guardrail reference works. Validate the full RAI
policy ARM ID and filtering behavior. Provider OIDC authentication does not
automatically authenticate a CLI readiness helper; configure both intentionally.

Keep secrets out of variables, environment maps, state, saved plans and CI output.
Terraform can retain values even when marked sensitive. Prefer managed identity
and connection-based secret resolution where needed.

Private networking is a separately scoped deployment profile. If school policy
requires it, validate Foundry/API/frontend compatibility, DNS, subnet capacity and
registry tier requirements before quoting costs; Basic ACR does not provide all
private-network features.

## 12. Milestones, dependencies and acceptance

Effort below is a provisional engineering estimate, not a quote or guaranteed
calendar schedule. Re-estimate after M0. External tenant permissions, quota,
privacy review and paid-test authorization are lead-time risks.

| Milestone | Owner | Prerequisites | Indicative effort |
|---|---|---|---|
| M0: decisions and compatibility spikes | Backend/AI + platform + school owner | Plan review | 3-5 person-days |
| M1: Terraform platform foundation | Platform | M0 | 3-4 person-days |
| M2: domain state, approvals and API contracts | Backend | M0 | 4-6 person-days |
| M3: artifact bridge and recoverable job execution | Backend | M2 | 5-8 person-days |
| M4: hosted skill agent and paid-stage governance | Backend/AI | M0, M2, M3 | 5-8 person-days |
| M5: teacher portal and human review | Frontend + backend | M2; M3/M4 for integrated completion | 7-10 person-days |
| M6: release pipeline and cloud integration | Platform + backend/frontend | M1, M3, M4, M5 | 4-6 person-days |
| M7: acceptance, quality, recovery and load | QA + engineers + teachers | M6 | 4-6 person-days |
| M8: controlled school pilot and handover | School owner + engineers | M7 | 3-5 person-days |

Total indicative effort: 38-58 person-days before contingency and deferred
extensions. Parallel work reduces calendar time only where dependencies permit.
Do not advertise a fixed delivery date before M0 and the school approval schedule.

### M0: decisions and compatibility spikes

Deliverables:

- Confirm school tenant/access policy, supported regions, student-data permission,
  retention/deletion rules and required private networking.
- Confirm pilot languages, exam types, class/page limits, accessibility priorities,
  reports and acceptable marking quality.
- Confirm approved models/quotas, chat/stage allowances and paid-test budget.
- Demonstrate a local synthetic Framework skill load and one safe tool call.
- Demonstrate adapter readiness, Responses contract, background/resilience API
  compatibility and graceful shutdown with mocked inference.
- Demonstrate a minimal engine-workspace hydration/checkpoint round trip.
- Choose and review pinned cloud dependencies and packaging boundary.

Acceptance: recorded decisions and compatible local spike; unresolved preview,
identity, protocol or persistence assumptions are resolved before cloud design
is finalized. No student data or paid inference is needed for local spikes.

### M1: Terraform platform foundation

Deliverables: separate state/configurations, dev/pilot/prod naming, least-privilege
identity matrix, approved resource plans, registry connection, API/frontend
hosting, private storage/queues, monitoring and cost settings.

Acceptance: validation and approved dev apply; unauthorized data/model access is
denied; destroy/change plans identify protected resources. Creating chargeable
resources requires separate authorization.

### M2: domain state, approvals and API contracts

Deliverables: versioned schemas, transition table, exam authorization, ETag
handling, approval/quote transactions, budget reservations, outbox, API errors and
OpenAPI contract. Implement isolated control/worker permissions.

Acceptance: missing/stale/forged approval, cross-teacher access, invalid review,
changed pricing and duplicate/conflicting submissions fail closed in offline
tests. An approval survives process restart and cannot be written by a worker.

### M3: artifact bridge and recoverable execution

Deliverables: bounded upload/finalization, scoped workspaces, immutable artifacts,
exact configuration/provenance restoration, engine adapter, dispatch leases,
checkpoint persistence, cancellation and unknown-outcome paths.

Acceptance: synthetic exam inputs/output survive worker replacement; queue
duplicates do not start a second authorized job; known completed calls are reused;
unknown provider outcomes pause rather than silently rebill. Existing local
workflow tests remain unchanged/passing.

### M4: hosted skill agent and paid-stage governance

Deliverables: immutable runtime skill, typed tools, request-scoped agent factory,
Responses server, stored/resilient background handling, role-scoped job context,
stage/chat consent and budgets, reviewed retry settings and redacted telemetry.

Acceptance: the actual runtime loads the relevant skill and reference; no
unrestricted script runner exists; the agent cannot approve review or invoke paid
work without matching current consent. Resumption reconstructs state from durable
records, not assumed conversational memory.

### M5: teacher portal

Deliverables: all pilot screens in section 6, server-backed save/review actions,
crop-coordinate correctness, identity/mark validation, bulk-action preview,
history/conflict handling, status/recovery UI and authorized exports.

Acceptance: a nontechnical teacher completes a synthetic exam without YAML,
credentials or commands. Browser refresh/new login preserves work; stale tabs
cannot overwrite current review; all required human decisions are explicit.
UI work can start against the M2 contract while M3/M4 proceed.

### M6: release pipeline and cloud integration

Deliverables: reproducible builds, provider/cloud locks, image digests, version
pinning, environment approvals, readiness checks, scoped identities, synthetic
cloud smoke suite, guardrail tests and rollback procedure.

Acceptance: a fresh approved dev environment can be deployed from reviewed code;
candidate promotion and rollback are demonstrated. Health, authorization and
guardrail behavior are checked independently. Paid smoke calls remain opt-in.

### M7: acceptance and workload evaluation

Deliverables: the matrix in section 13, measured sizing/cost sheet, supported
workload envelope, accessibility review, failure drill results, dependency
assessment and teacher quality evaluation.

Acceptance: all mandatory gates pass. Any unresolved tenant isolation,
approval-bypass, data-loss or uncontrolled-paid-retry defect blocks the pilot.
The school accepts observed marking behavior and teacher-review workload.

### M8: controlled pilot and handover

Deliverables: administrator setup guide, teacher quick-start, recovery/privacy
runbooks, dashboards, access roster, support ownership and documented limits.

Acceptance: authorized pilot teachers complete agreed workloads; billed/recorded
usage differences are disclosed; backup/restore and deletion are exercised.
Approve wider use separately after the school reviews pilot evidence.

### Later extensions

Email requires recipient/attachment preview, independent delivery approval,
delivery journals and ambiguous-send recovery. Teams requires tenant publication
approval and channel authorization, with detailed review still opening the web
app. Multi-school hosting requires a new isolation/provisioning/billing design,
not simply adding a school ID to paths.

## 13. Verification matrix

Use public/synthetic fixtures by default. Real student evaluation requires school
authorization and a data-handling plan. Do not fabricate observed conversations,
model results or human approvals in demos.

| Area | Mandatory cases | Pass condition |
|---|---|---|
| Existing engine | Current offline suite; grading, pricing, attendance, regions, regrading, workflow | No cloud-caused regressions or mandatory cloud dependency |
| Identity/access | Wrong tenant, unauthorized teacher, guessed exam/artifact/job, forged principal, revoked grants | No data disclosure or permitted mutation |
| Uploads | Oversize, malformed PDF, fake extension, duplicate finalization, hostile filename, pixel/page limits | No paid inference; bounded rejection; no traversal |
| Review | Missing rows, duplicate/absent IDs, leading zeros, failed/flagged marks, NaN/infinity/out-of-range, bulk preview | Existing approval semantics preserved |
| Concurrency | Two tabs, simultaneous approvals, reused idempotency key, duplicate queue messages, expired lease | Conflict or safe convergence; no lost current edits |
| Approval provenance | Changed rubric/boxes/review/model/pricing, stale quote, worker attempt to approve | Rejection and correct new-review action |
| Cost gates | No consent, unavailable/changed rates, chat opt-out, parallel reservations, unknown usage/outcome | No unauthorized paid request; unknown is not zero |
| Skills | Actual provider load/resource read, uploaded instruction injection, arbitrary tool/path request | Scoped allowlisted behavior; no manufactured approval |
| Recovery | Crash before/after queue send, provider submission, result commit, checkpoint upload and completion | Valid continuation or explicit unknown-outcome pause |
| Cancellation | Browser disconnect, explicit cancel, SIGTERM, synchronous thread still running | Honest state; durable progress; no new work after acknowledged stop |
| Runtime | Contract endpoints, SDK reentry, history isolation, session expiry/new worker | Readiness and compatible reconstruction without memory assumptions |
| Reports | Changed approval, wrong child run, unauthorized download, expired delegated URL | Only valid authorized exports |
| Terraform/release | Fresh environment, no-op apply, wrong digest, inactive version, competing writer, rollback | Controlled ownership and verified candidate |
| Guardrails | Valid/invalid policy reference and approved synthetic filtering test | Effective policy behavior, not merely active status |
| Privacy/retention | Logs/referrers, export contents, expired data, backup retention, erasure | Policy applied with no hidden retained copies |
| Browser UX | Keyboard flow, zoom/DPR coordinates, network loss, refresh, blind mode, conflicts | Usable review with preserved state |
| Marking quality | Representative handwriting/layout/language; identity and crop errors; teacher disagreement | School-defined thresholds met; limitations disclosed |
| Capacity/cost | Synthetic 4-, 30-, 50-student cases, two pages/five questions; agreed concurrency | Measured envelope, memory peaks, duration and cost; no invented linear forecast |

Suggested provisional UX target: metadata/review API p95 below two seconds under
the agreed pilot concurrency, excluding uploads, cold starts and long-running
jobs. Confirm the target at M0. Model-job duration and quality thresholds must be
measured before promising an SLA.

Engine regression command, run in the engine checkout:

```sh
uv run --frozen python -m unittest discover -s tests -v
```

Initial application checks, run in this repository:

```sh
uv run --frozen --extra dev pytest
uv run --frozen --extra dev ruff check .
uv run --frozen --extra dev ruff format --check .
```

New cloud tests must be separately selectable and offline by default. Browser
tests use synthetic data and fake providers; paid cloud tests require an
explicit environment and approved allowance. Run existing formatters/linters
and add cloud/frontend tooling only with the corresponding reviewed manifests.
Terraform checks include `terraform fmt -check`, `terraform validate` and
reviewed environment plans; validation alone does not exercise the data plane.

## 14. Operations, rollout and rollback

Monitor non-sensitive job stage/duration, queue age, failures, unknown outcomes,
recovery count, budget reservations, recorded token usage, active session-hours,
CPU/memory and approval conflicts. Use opaque correlation IDs; keep protected
review/audit data out of general traces.

Required runbooks:

- Pause new paid work; explain consequences for already-issued requests.
- Recover a poisoned/stalled job without blindly rerunning inference.
- Reconcile an unknown provider outcome with Azure billing and teacher decisions.
- Restore immutable artifacts/control state and validate every approval hash.
- Roll back an agent/frontend/API release without invalidating active checkpoints.
- Rotate/revoke access; verify teacher and workload authorization.
- Expire exams/uploads/caches according to policy, including backup copies.
- Investigate an unauthorized-access or unintended-charge incident.

Roll out through local synthetic tests, approved development deployment,
authorized synthetic cloud evaluation, limited school pilot and separately
approved wider use. Real student data is not needed to prove infrastructure
readiness.

Pin each job to a compatible agent release/model configuration. Deployment must
not silently move in-flight recovery onto incompatible code or newer models.
Keep schema migration/version compatibility explicit; rollback must not erase
approved records. Do not destroy storage/identities as a routine release step.

## 15. Definition of done and unresolved approval gates

The pilot is implementation-complete only when:

1. The teacher journey works end to end with genuine runtime skills and no
   technical setup for teachers.
2. Human input, cost, score and any enabled delivery approvals are enforced
   independently of the model.
3. Exam access and worker/control separation pass their negative tests.
4. Durable review, dispatch, crash recovery and unknown-outcome handling pass
   failure injection without misleading billing guarantees.
5. Existing local grader/skill behavior is preserved.
6. Terraform/CI deployment, candidate validation and rollback are demonstrated.
7. Supported workloads, observed costs/quality and limitations are documented.
8. The school approves privacy/retention, paid usage and pilot acceptance.
9. Reviewed code is committed/deployed only after explicit authorization.

Before implementation leaves M0, resolve: school tenant and teacher roles;
region/data-residency and private-network requirements; retention/erasure;
languages/layouts/class limits; acceptable grading quality; approved model and
hosting dependency versions; budgets/paid-test authorization; required exports;
and who owns school administration and support.

These are recorded deployment gates, not assumptions the agent may decide for
the school.

## 16. Sources and companion design documents

Official sources reviewed on 2026-11-24; recheck before implementation/deployment:

- [Foundry hosted agents and billing](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Hosted-agent runtime contract](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract)
- [Long-running execution and resilience](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/long-running-agent-resilience)
- [Terraform hosted-agent deployment](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/deploy-hosted-agent-terraform)
- [Framework runtime skills](https://learn.microsoft.com/en-us/agent-framework/agents/skills)
- [Framework hosted-agent integration](https://learn.microsoft.com/en-us/agent-framework/hosting/foundry-hosted-agent)
- [Hosted-agent permissions](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-permissions)
- [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)
- [Static Web Apps pricing and plan limitations](https://azure.microsoft.com/en-us/pricing/details/app-service/static/)
- [Container Registry pricing and tier limitations](https://azure.microsoft.com/en-us/pricing/details/container-registry/)

Engine repository companions, pinned to the reviewed dependency commit:

- [Existing flow and architecture][engine-flow]
- [Model configuration and caching][engine-model-config]
- [Score review and approval][engine-score-doc]
- [Attendance and targeted regrading][engine-attendance-doc]
- [Regions and layout][engine-regions-doc]
- [Telemetry and cost reporting][engine-telemetry-doc]
- [Cleanup and retention][engine-cleanup-doc]
- [Email distribution][engine-email-doc]
- [Existing test practices][engine-testing-doc]

[engine-workflow]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/workflow.py
[engine-grading]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/grading.py
[engine-attendance]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/attendance.py
[engine-rubric]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/rubric.py
[engine-regions]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/regions.py
[engine-editor]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/editor.py
[engine-score-editor]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/score_editor.py
[engine-grade-review]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/grade_review.py
[engine-run-context]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/run_context.py
[engine-pricing]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/pricing.py
[engine-telemetry]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/src/handwriting_grader/telemetry.py
[engine-skill]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/skills/handwriting-grading/SKILL.md
[engine-flow]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/design-logic-and-flow.md
[engine-model-config]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/model-configuration-and-caching.md
[engine-score-doc]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/score-review-and-approval.md
[engine-attendance-doc]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/attendance-and-regrading-design.md
[engine-regions-doc]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/region-and-layout-architecture.md
[engine-telemetry-doc]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/telemetry-and-cost-reporting.md
[engine-cleanup-doc]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/cleanup-and-retention-design.md
[engine-email-doc]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/email-distribution-architecture.md
[engine-testing-doc]: https://github.com/wongcyrus/azure-handwriting-grader-skills/blob/3b155f9232cb0730587d89677c932ea049dd7f71/docs/testing-skills.md
