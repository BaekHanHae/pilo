# AI Gateway and PILO-Skills Audit — 2026-11-14

## Scope and evidence

- Source: `BaekHanHae/pilo` draft PR #1 (`feature/pilo-skills-ai-gateway`) at `13cd1481290bf4747f7556f13496e58e016c4f1d`.
- Core baseline: `main`, PILO Core 0.3.1 and schema 2.
- Latest observed GitHub Actions run at audit start: [43466371145](https://github.com/BaekHanHae/pilo/actions/runs/43466371145), all four macOS/Ubuntu × Python 3.11/3.14 jobs successful.
- Existing tests use minimal schema stubs for important AI authorization/claim/finalization paths; successful jobs **do not** establish production Core/schema-3/E2E readiness.
- No local full checkout or real AI CLI run is claimed for this audit.
- This branch is isolated; do not merge the feature branch or activate any candidate migration without review.

## Severity and findings

| ID | Priority | Finding and evidence | Remediation and required proof |
|---|---|---|---|
| GW-01 | P0 integration blocker | `preflight_ai_execution`, `claim_ai_attempt`, `finalize_ai_attempt` call `core._authorize(..., "ai.run", ...)`; current Core requires an RBAC permission and feature tests mostly substitute fake `_authorize`. No integrated grant/provisioning of `ai.run` verified. | Add an explicitly scoped, default-deny AI permission in a reviewed additive migration; exercise a real Core RBAC principal with denied and granted cases. Never bypass Core permissions. |
| GW-02 | P0 safety blocker | `ai_finalize.py` revalidates the approval before writing the phase; revocation after possible external effects raises and leaves an attempt RUNNING. The pure `ai_reconciliation.py` helper does not persist uncertain states. | Define a separate Core-authorized, fenced transaction to persist `UNCERTAIN` and audit even if the original execution approval was revoked; do not auto-retry, and test crash/restart/race scenarios. |
| GW-03 | P0 safety blocker | `ai_evidence.py` hashes bytes, but does not prove project/attempt provenance or observed worktree effects. `finalize_ai_attempt` accepts a caller-selected `ContentStore`, and checks its digest outside the write transaction. | Bind evidence to attempt/project/snapshot and a trusted configured Core store, then reconcile pre/post Git/worktree state. Revalidate stored provenance and identity in Core-owned transaction; include substitution/race tests. |
| GW-04 | P1 migration blocker | `0003_ai_attempt_candidate.sql` is dormant; `Core.__init__` accepts only schema 1/2, and `migrations.py` upgrades only 1→2. | Build a *separately approved* 2→3 migrator with backup, history/checksum/config recovery, and isolated migration tests. Never rewrite migrations 0001/0002. |
| GW-05 | P1 cross-project integrity | Candidate `AIAttemptRecord.project_id` and `execution_id` have separate FKs; database constraints alone do not ensure they belong together. Same issue applies to optional approval/checkpoint binding. | Enforce same-project/execution composite constraints where possible, and revalidate authorization/scope transactionally. Test cross-project tampering with real schema. |
| GW-06 | P1 scheduler/integration | Existing CODE scheduler may retry timeouts; AI gateway is deliberately not attached to it, and no real process spawn, bounded workspace sandbox, lifecycle persistence, crash reconciliation, or CLI E2E is implemented. | Implement separate AI attempt dispatch guarded by Core claim, fencing, effect classes, timeout/output controls, durable uncertainty and operator review; smoke-test with an inert fake CLI before any external adapter. |
| GW-07 | P1 interface defect (fixed here) | `ai_finalize.py` annotated `binding: AIBinding | None` without importing `AIBinding`. Deferred evaluation masks the import issue, but `typing.get_type_hints` fails. | Import `AIBinding`, add regression test for introspected annotations. |
| GW-08 | P1 verification gap | Existing AI SQLite tests use local `FakeCore` and simplified tables, not the real migration + Core permission stack. Draft handoff and PR documentation contain superseded statements about tests/CI. | Run real permission/schema integration, full CI, and real CLI failure scenarios; update docs to reference each verified commit and distinguish tests from proven security properties. |

## Investigation and implementation order

1. **Permission and scope**: model `ai.run` and explicit role provisioning with default deny. Confirm permissions in genuine schema-2/3 DB. Keep feature disabled.
2. **Durable failure**: introduce an independent, authorized `UNCERTAIN` transition and append-only reconciliation audit. Guard with attempt id, revision, fencing token, project and execution identities; never translate a revoked approval to a successful completion.
3. **Evidence ownership**: Core-selected content store, trusted provenance record, CAS hash verification, immutable attempt linkage, Git/worktree effect observation and conservative handling of unknown external effects.
4. **Additive migration**: review schema-3 FK relationships, exact schema history and config recovery. Test clean 1→2→3, existing 2→3, backup restore, failure halfway, FK violations and concurrent claims.
5. **CLI adapter boundaries**: vendor-neutral contract, explicit allowlist, fixed executable/arguments, bounded environment/output/time, separate scheduler, no automatic retries for effects; real E2E across adapters only after safe fake adapter tests.
6. **Documentation and release**: reconcile formal English specification with actual repository implementation; record tested SHA and platform matrix, require human review prior to merging the draft.

## Acceptance checklist

- [ ] Real Core principal denied by default, explicit scope-bound grant works, revocation blocks new claims.
- [ ] Effects already possibly incurred always persist UNCERTAIN and audit, including revocation and timeout.
- [ ] Duplicate finalize/reconcile, stale fence/revision, restarted process, and cross-project evidence all fail closed.
- [ ] Schema-3 migration validates and backups restore; 0001/0002 remain byte-identical.
- [ ] Real CLI fake-adapter E2E + subprocess environment bounds + cancellation/restart tests pass.
- [ ] Every supported Python/macOS/Linux CI job passes on the exact proposed commit.
- [ ] PR #1 remains draft until safety and integration gates are met.

## Related resources

- [Draft PR #1](https://github.com/BaekHanHae/pilo/pull/1)
- [AI gateway handoff](https://github.com/BaekHanHae/pilo/blob/feature/pilo-skills-ai-gateway/docs/ai_gateway_development_handoff_2026-11-11.md)
- [Candidate schema](https://github.com/BaekHanHae/pilo/blob/feature/pilo-skills-ai-gateway/pilo_core/sql/0003_ai_attempt_candidate.sql)

This report identifies code defects and integration gaps; it does not imply any unexecuted test has passed.
