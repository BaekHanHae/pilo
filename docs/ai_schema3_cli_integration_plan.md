# Schema 3 and CLI integration review candidate

Status: offline validation only. Production Core still accepts versions 1/2 and
its CLI cannot activate schema 3. Existing migrations 0001/0002 are unchanged.
This document does not authorize production migration or agent execution.

## Additive persistence and RBAC

The dormant 0003 candidate adds a unique project/execution key, composite foreign
keys for attempt ownership, step and checkpoint ownership, and evidence ownership.
Attempt identity and review/evidence records are immutable. Fence/revision phase
triggers prevent terminal attempts returning to PENDING or RUNNING. Permission
inventory contains ai.run, ai.evidence and ai.reconcile with no role grants.
Existing explicit OS-operator provisioning supports project-scoped grants; tests
exercise actual Core authorization and cross-project denial. Execution permission
never implies evidence registration or reconciliation permission.

## Offline rehearsal

`pilo_core.ai_schema_rehearsal.rehearse(config, new_artifact_directory)` validates a
schema-2 installation, creates a checksummed SQLite backup, copies that snapshot,
and applies candidate DDL transactionally to the copy. It writes candidate history,
audit and user_version 3 only in the copy, checks exact schema shape, migration
checksums, integrity, foreign keys and the audit chain, then atomically publishes
an offline report. It never changes the installation database or configuration.
The report explicitly says production_compatible=false and ai_execution_enabled=false.

`resume=True` validates journal identity, backup digest and the committed candidate
before recovering report publication. It never reapplies DDL. A crash before DDL
commit leaves an incomplete artifact that is rejected; use a new artifact directory
and retain the failed artifact for diagnosis. No source rollback is needed because
the source was never upgraded. Candidate source checksum drift, corrupt backup,
invalid history or schema drift prevents recovery.

Executed tests cover fresh 1→2 initialization followed by the 2→3 copy rehearsal,
source byte preservation, backup tampering, post-commit publication interruption,
staged report replacement, schema/version tampering and real RBAC provisioning.
This does not validate a production configuration upgrade. A production migrator
still needs an independently reviewed backup/recovery runbook and explicit approval.

## Vendor-neutral CLI contract

`ai_cli_contract.py` prepares a fixed argv tuple with no shell, executable hash,
explicit workspace, separate private HOME/TMPDIR, and a minimal environment without
inherited credentials. The payload travels on stdin using json-stdin-v1 or
text-stdin-v1. A prepared invocation carries timeout and output budgets; it is
configuration data and cannot authorize execution. `dispatch_ai` always denies.
Fake CLI tests exercise both input formats, literal shell characters, environment,
workspace selection, executable substitution and invalid budgets.

There is deliberately no production runner enforcing those budgets yet. Environment
filtering is not filesystem/network isolation. Before real adapters are admitted:

1. Add a separate AI scheduler, lease ownership and a unique active-attempt constraint;
   keep the existing retrying CODE scheduler independent. On timeout/crash/revocation,
   deliver a fenced UNCERTAIN observation under ai.reconcile. Never retry the process.
2. Enforce process-group cleanup, streaming output caps, stdin limits, timeouts,
   executable identity at spawn and an OS-enforced workspace/network sandbox.
3. Bind observed output trees to reviewed write scopes and immutable approval context.
   Unchanged Git observations cannot prove absence of transient or network effects.
4. Validate two independently implemented real agent adapters in isolated disposable
   projects, without production credentials, only after the preceding checks pass.
   Record versions, command contracts, environment, effects, timeout behavior and
   evidence provenance. No vendor-specific session becomes Core authority.
5. Review migration and CLI integration before enabling any feature flag. No default
   provisioning grants AI authority and no CLI option currently enables dispatch.

Real agent adapter E2E, production migration recovery, and the separate scheduler
remain unresolved Issue #5 gates. Issues #3–#5 should remain open until their full
integration acceptance criteria have been reviewed.
