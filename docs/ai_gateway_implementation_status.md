# AI Gateway implementation status

AI execution remains disabled by default. Schema 3 is a dormant candidate;
production Core accepts only schema 1/2. No production migration, merge or
external agent execution is authorized by these changes.

## Issue 3: fenced recovery

`ai_recovery.py` adds atomic RUNNING → UNCERTAIN and operator review transactions.
The distinct, explicitly provisioned `ai.reconcile` permission is required. Active
execution approval and `ai.run` are deliberately unnecessary for safety recovery.
All identities, fence, revision, authoritative execution ownership and the audit
chain are checked inside Core's write transaction. Duplicate/stale deliveries
fail closed. Reviews are immutable and cannot mark an attempt completed or put
it back in PENDING. MARK_FAILED never grants execution or retry authority.

Callers must deliver a safety observation after timeout, revocation, crash or
failed verification. Failure to persist must block further execution; only the
observation transaction may be redelivered, never the external process. Automatic
startup discovery and a separate AI scheduler remain integration work.

Tests install the candidate only in temporary databases. A test-only Core subclass
accepts the augmented schema shape while retaining real Core transactions, RBAC,
audit validation and SQLite foreign keys. This is not schema-3 migrator validation.

## Remaining release gates

- Issue 4: conservative provenance checks are implemented for unchanged READ_ONLY
  worktrees. Approved write-output contracts and OS/network isolation are still
  release blockers; external/write results cannot be finalized.
- Issue 5: reviewed offline migration/recovery, composite schema binding, scheduler,
  bounded vendor-neutral CLI adapters and two real adapter integration checks.
- No real external AI CLI execution has been verified.

## Executed verification

- Baseline `13cd1481290bf4747f7556f13496e58e016c4f1d`: 155 unittest tests,
  successful with one skipped test.
- Issue 3 focused run: 85 AI tests passed before the additional revocation case.
- `python3 tools/validate_schema.py --report /tmp/pilo-sql.json`: 143 tests passed,
  integrity check OK, no foreign key errors.
- Exact commits and final regression/CI results are recorded in the PR and follow-up
  entries below; no pending check is claimed as passed.

## Issue 4: conservative provenance gate

Evidence registration requires separately provisioned `ai.evidence` permission.
Core chooses the installation content store; a caller-provided store is rejected.
Immutable metadata binds the evidence ID and content digest to project, execution,
step, attempt, fence, revision and sealed checkpoint. Finalization rereads bytes
and scope inside the write transaction, then observes the current Git repository.
Missing/changed objects, changed HEAD, dirty/untracked/ignored files, index flags,
timeout and substituted bytes fail closed. Evidence is content plus a Core
observation, never a statement that an agent's text proves execution success.

Only unchanged READ_ONLY results are eligible. WORKTREE_WRITE and EXTERNAL
remain denied, even if text claims success. SQLite cannot lock filesystem or
network state: observation does not prove absence of transient changes or network
effects and cannot defeat an uncooperative concurrent OS writer. The feature must
remain disabled until process isolation and exclusive workspace ownership pass
integration tests. Recovery observations can still persist UNCERTAIN.

Issue 3 exact commit: `f79419501e67d1bf9b9030d864a8b2a9b7445b7c`.
Local regression: 163 tests successful, one skipped. GitHub Actions run
[43585307699](https://github.com/BaekHanHae/pilo/actions/runs/43585307699)
completed successfully for that commit.
