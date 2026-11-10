# AI attempt persistence — schema 3 design candidate

Status: **PROPOSAL ONLY**. Do not run as a migration. PILO Core 0.3.1 supports schema 2 and validates exact migration history/checksums. Adding SQL without updating the Core migrator, configuration, and validation would break existing installations.

## Verified schema-2 constraints

- `StepAttempt.status` permits RUNNING, COMPLETED, FAILED, INTERRUPTED, CANCELLED; it **does not permit UNCERTAIN**.
- `StepScheduling.queue_state` permits PENDING, BLOCKED, READY, RUNNING, WAITING_APPROVAL, RETRY_WAIT, COMPLETED, FAILED, CANCELLED, SKIPPED; it **does not permit UNCERTAIN**.
- Existing `ApprovalGrant` and `ApprovalRequest` are Core-owned and require scoped validation.
- The existing `scheduler_tick` automatically retries selected CODE timeouts. Do not route AI attempts through it.

## Proposed additive schema 3 objects (not executable DDL)

`AIExecutionAttempt`
- `attempt_id` primary key; FK to Core `StepAttempt` only after introducing an AI-specific scheduling path compatible with its status checks.
- `project_id`, `execution_id`, `step_id`, `adapter_id`, `effect_class`, `fencing_token`.
- `phase`: PENDING/RUNNING/COMPLETED/FAILED/UNCERTAIN/CANCELLED.
- `approval_id`, `checkpoint_id`, `input_digest`, `result_evidence_ref`.
- `created_at`, `updated_at`, `version` for optimistic compare-and-swap.

`AIReconciliationReview`
- Immutable `review_id` primary key, `attempt_id`, `expected_fencing_token`, `reviewer_principal_id`, `decision`, `evidence_ref`, `created_at`.
- No deletion or rewriting of review history. Reviews must be auditable.
- Reconciliation cannot declare COMPLETED based on a text-only claim.

## Required transaction boundaries

1. **Claim**: Core checks principal, project, immutable plan binding, allowlisted adapter, scope-limited approval, checkpoint, resource reservation; writes RUNNING and new fencing token atomically.
2. **Execute**: adapter runs outside the DB transaction, in a bounded workspace. The adapter cannot grant permissions.
3. **Finalize**: Core verifies active fence and lease, output CAS hash, workspace state, approval validity; atomically commits result and audit.
4. **Unknown effects**: persist UNCERTAIN and block automated retries, even after timeout or process crash.
5. **Review**: separate operator-authorized transaction appends review with immutable evidence. The next action requires a new explicit execution plan/approval if effects cannot be proven absent.

## Required implementation before any SQL migration

- Decide whether to extend existing StepAttempt/StepScheduling CHECK constraints by table rebuild or introduce separate AI scheduling tables. Both require schema-3 migration and rollback/recovery testing.
- Implement explicit backup, migration checksum, config reconciliation and Core health verification; never edit 0001/0002.
- Add tests: migration 2→3, clean install 1→2→3, interrupted migration recovery, FK integrity, stale fencing, concurrent claims, approval revocation, restart persistence, and UNCERTAIN no-retry.
- Keep AI execution disabled until these pass and real CLI behavior is evaluated.

## Security boundary

`ai_execution_policy.py`, `ai_attempt_state.py`, and `ai_reconciliation.py` are isolated, pure validation helpers. Their success is not proof of authenticated identity, durable approval, actual evidence integrity, or permission to spawn a process.
