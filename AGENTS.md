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
- No Azure deployment, paid inference, real student data or email without the
  relevant explicit approvals.
- Local development is localhost-only and synthetic-data-only. SQLite is not the
  production storage/authorization architecture.
- Teacher approval is not a model tool. Do not remove ownership, ETag, artifact
  hashes, engine provenance or validation gates to make tests pass.
- Do not replace real engine integration tests with fake validators. Core tests
  intentionally isolate state/auth; engine-marked tests exercise the pinned engine.

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

Implementation currently includes untracked files. Check `git status --short`;
an empty `git diff` does not mean there is no pending code.
