# PILO AI Gateway — Development Handoff (2026-11-11)

## Resume instruction
The user sends **1** to mean **continue the next implementation step**. Continue sequentially, explain in Korean, write repository code and docs in English. Do not request confirmation except for consequential authorization or design decisions.

## Repository safety
- Repository: `BaekHanHae/pilo`
- Working branch: `feature/pilo-skills-ai-gateway`
- Draft PR: https://github.com/BaekHanHae/pilo/pull/1
- Do **not** merge, modify `main`, modify Master Specification, or activate the schema-3 migrator/AI CLI without explicit approval.
- Existing Core 0.3.1 / SQLite schema 2 is active. Schema-3 SQL is only a dormant proposal.

## Implemented on feature branch
- `pilo_core/ai_execution_policy.py`: fail-closed AI admission.
- `pilo_core/ai_attempt_state.py`: attempt lifecycle and UNCERTAIN semantics.
- `pilo_core/ai_reconciliation.py`: pure review decisions.
- `pilo_core/ai_scope.py`: project, step, checkpoint, approval binding checks.
- `pilo_core/ai_core_gate.py`: authorization + scope preflight.
- `pilo_core/ai_claim.py`: explicit attempt ID, BEGIN IMMEDIATE/CAS fence/revision, same-transaction audit.
- `pilo_core/ai_evidence.py`: digest and size validation of actual bytes.
- `pilo_core/ai_finalize.py`: fenced finalization, actual Core ContentStore digest verification, scope and approval revalidation, same-transaction audit.
- `pilo_core/sql/0003_ai_attempt_candidate.sql`: **not active**.
- Associated `tests/test_ai_*.py` files; ~70 new tests authored, **not verified as executed**.

## Latest changes
- `ai_finalize.py` now reads `effect_class`, `approval_id`, `checkpoint_id` from `AIAttemptRecord` and reruns `validate_ai_scope` before finalization. It rejects missing binding for side-effecting effects.
- `tests/test_ai_finalize_sqlite.py` added two cases for invalid effect class and missing approval binding.
- Actual ContentStore is `pilo_core/storage.py` with `put(bytes)->sha256`, `get(digest)->bytes`; it validates digest and rejects symlinks.

## IMPORTANT: Known limitations and issues to address first
1. **Execute tests, do not assume pass**. Some tests may fail due to actual schema or API signatures. Use local checkout or CI and report verified results only.
2. **Approval revocation and UNCERTAIN**: if an external side effect may already have happened, a revoked approval cannot simply roll it back. Design a durable fail-closed transition to UNCERTAIN and review, with transactional audit. The existing `ai_reconciliation.py` is a pure state helper, not a persisted transaction.
3. **Finalize evidence provenance**: hash integrity does not prove evidence belongs to this project/attempt or that worktree effects match. Add immutable provenance/binding and trusted Core-owned evidence reads.
4. **Finalize currently validates CAS bytes before opening the write transaction**; consider race semantics, scope authorization and evidence ownership. ContentStore.get validates content hash, but evidence metadata binding is missing.
5. **Finalization with revoked approval currently raises without persisting UNCERTAIN**, leaving RUNNING. Must distinguish terminal process observation from approval failure.
6. **Schema-3 candidate** has project_id and execution_id independent FKs; ensure cross-project binding at transaction boundary, and test real schema-2 migration. Do not activate until reviewed.
7. **Potential API mismatch**: `validate_ai_scope` uses schema-2 tables and columns; verify against actual schema. SQLite mock fixtures do not establish full Core integration.
8. **Evidence verification parameter** `content_store` is accepted by finalize. Ensure only trusted Core-owned store can be supplied by callers at service boundary; Python type check alone is not a security boundary.
9. **Security**: external side effects are not undone by a failed Finalize. Never auto retry UNCERTAIN.

## Next implementation sequence
1. Read latest branch files, implement atomic persisted UNCERTAIN and reconciliation (fence/revision/permission/scope/audit, no automatic completion).
2. Add tests for revocation during execution, stale fence, duplicate review, audit rollback and cross-project scope.
3. Run real tests; fix failing tests and integration gaps.
4. Validate schema-3 migration in an isolated copy of schema-2; request authorization before activation or Master Spec edits.
5. Keep Draft PR until integration and security checks pass.

## Working preferences
macOS M1 16 GB, Python with uv, local-first SQLite, low cost, CLI/agent-agnostic skills, deterministic code where possible. Korean discussion; English project documentation.
