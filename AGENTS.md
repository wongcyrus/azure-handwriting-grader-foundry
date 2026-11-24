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
  and explicitly approves them. The existing public commit is documentation only.
  Foundation `e8ad9cf`, attendance `708cff1` and region review `9d05ab0` are local
  and unpushed; subsequent changes still need separate review and approval.
  Teacher canvas is committed as `9f8e2f0`, also local only.
  Owned-exam selection is committed as `184875d`, also unpushed.
  Input setup/review is committed as `bff8e5b`, also unpushed.
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
