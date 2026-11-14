-- PILO AI execution persistence, schema-3 CANDIDATE ONLY.
-- DO NOT APPLY to production or add to the active migrator until reviewed.
-- Requires existing schema 2 and SQLite STRICT table support.
-- Existing CODE StepAttempt and StepScheduling tables are unchanged.
CREATE TABLE AIAttemptRecord (
    attempt_id TEXT PRIMARY KEY NOT NULL,
    project_id TEXT NOT NULL REFERENCES Project(project_id) ON DELETE RESTRICT,
    execution_id TEXT NOT NULL REFERENCES Execution(execution_id) ON DELETE RESTRICT,
    step_id TEXT NOT NULL,
    adapter_id TEXT NOT NULL CHECK(length(trim(adapter_id)) > 0),
    effect_class TEXT NOT NULL CHECK(effect_class IN ('READ_ONLY','WORKTREE_WRITE','EXTERNAL')),
    phase TEXT NOT NULL CHECK(phase IN ('PENDING','RUNNING','COMPLETED','FAILED','UNCERTAIN','CANCELLED')),
    fencing_token INTEGER NOT NULL DEFAULT 0 CHECK(fencing_token >= 0),
    approval_id TEXT REFERENCES ApprovalRequest(approval_id) ON DELETE RESTRICT,
    checkpoint_id TEXT REFERENCES Checkpoint(checkpoint_id) ON DELETE RESTRICT,
    input_digest TEXT NOT NULL CHECK(length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'),
    evidence_ref TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
    UNIQUE(execution_id, attempt_id),
    FOREIGN KEY(execution_id, step_id) REFERENCES ExecutionStep(execution_id, step_id) ON DELETE RESTRICT,
    CHECK (
        (phase = 'PENDING' AND fencing_token = 0)
        OR (phase <> 'PENDING' AND fencing_token > 0)
    )
) STRICT;

CREATE INDEX idx_ai_attempt_project_phase ON AIAttemptRecord(project_id, phase);
CREATE INDEX idx_ai_attempt_step ON AIAttemptRecord(step_id);

CREATE TABLE AIReconciliationRecord (
    review_id TEXT PRIMARY KEY NOT NULL,
    attempt_id TEXT NOT NULL REFERENCES AIAttemptRecord(attempt_id) ON DELETE RESTRICT,
    expected_fencing_token INTEGER NOT NULL CHECK(expected_fencing_token > 0),
    reviewer_principal_id TEXT NOT NULL REFERENCES Principal(principal_id) ON DELETE RESTRICT,
    decision TEXT NOT NULL CHECK(decision IN ('KEEP_BLOCKED','MARK_FAILED')),
    evidence_ref TEXT NOT NULL CHECK(length(trim(evidence_ref)) > 0),
    created_at TEXT NOT NULL
) STRICT;

CREATE INDEX idx_ai_review_attempt ON AIReconciliationRecord(attempt_id);

CREATE TRIGGER ai_review_immutable_update BEFORE UPDATE ON AIReconciliationRecord
BEGIN SELECT RAISE(ABORT,'Immutable AI review'); END;
CREATE TRIGGER ai_review_immutable_delete BEFORE DELETE ON AIReconciliationRecord
BEGIN SELECT RAISE(ABORT,'Immutable AI review'); END;
