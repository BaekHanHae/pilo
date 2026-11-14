"""Dormant fenced recovery transactions; execution approval cannot veto safety.

No process is launched or retried. Requires the reviewed candidate schema.
"""
from .ai_scope import validate_ai_scope
from .ai_reconciliation import ReconciliationRequest, ReviewDecision, validate_reconciliation


class RecoveryRejected(RuntimeError):
    """Recovery identity, fence, revision or evidence is invalid."""


def _attempt(core, db, actor, attempt_id, project_id, execution_id, step_id,
             fencing_token, expected_revision, phase):
    if any(not isinstance(v, str) or not v.strip() for v in
           (actor, attempt_id, project_id, execution_id, step_id)):
        raise RecoveryRejected("Missing identity")
    if (type(fencing_token) is not int or fencing_token <= 0
            or type(expected_revision) is not int or expected_revision < 0):
        raise RecoveryRejected("Invalid fence or revision")
    core._authorize(db, actor, "ai.reconcile", project_id)
    row = db.execute("""SELECT project_id,execution_id,step_id,phase,fencing_token,revision
        FROM AIAttemptRecord WHERE attempt_id=?""", (attempt_id,)).fetchone()
    if row != (project_id, execution_id, step_id, phase, fencing_token, expected_revision):
        raise RecoveryRejected("Stale attempt or identity mismatch")
    # Verify authoritative ownership, deliberately without execution approval.
    validate_ai_scope(db, project_id=project_id, execution_id=execution_id,
                      step_id=step_id, approval_id=None, checkpoint_id=None,
                      side_effecting=False)
    core._verify_audit(db)


def mark_ai_uncertain(core, *, actor, attempt_id, project_id, execution_id,
                      step_id, fencing_token, expected_revision, now, reason):
    """Persist unknown effects even after execution permission/approval revocation.

    Recovery authority is independently provisioned, never implicitly granted to
    an executor. Call after timeout, crash, failed verification or revocation.
    A failed transaction must be delivered again with the same fence/revision;
    it must never cause a process retry.
    """
    if any(not isinstance(v, str) or not v.strip() for v in (now, reason)):
        raise RecoveryRejected("Timestamp and reason required")
    with core.connection(write=True) as db:
        _attempt(core, db, actor, attempt_id, project_id, execution_id, step_id,
                 fencing_token, expected_revision, "RUNNING")
        result = db.execute("""UPDATE AIAttemptRecord SET phase='UNCERTAIN',
            evidence_ref=NULL,revision=revision+1,updated_at=?
            WHERE attempt_id=? AND phase='RUNNING' AND fencing_token=? AND revision=?""",
            (now, attempt_id, fencing_token, expected_revision))
        if result.rowcount != 1:
            raise RecoveryRejected("Concurrent recovery")
        core._audit(db, actor, "AI_ATTEMPT_UNCERTAIN", project_id,
                    dict(attempt_id=attempt_id, execution_id=execution_id,
                         step_id=step_id, fencing_token=fencing_token,
                         expected_revision=expected_revision, reason=reason), now)


def reconcile_ai_attempt(core, *, actor, review_id, attempt_id, project_id,
                         execution_id, step_id, fencing_token, expected_revision,
                         now, evidence_ref, decision):
    """Append an immutable review; no completion or return to PENDING allowed.

    Review evidence is an operator statement, not proof of successful execution.
    MARK_FAILED closes the attempt but never authorizes another execution.
    """
    if any(not isinstance(v, str) or not v.strip() for v in (now, review_id)):
        raise RecoveryRejected("Review identity and timestamp required")
    validate_reconciliation(ReconciliationRequest(
        attempt_id, fencing_token, fencing_token, "UNCERTAIN", actor,
        evidence_ref, decision))
    with core.connection(write=True) as db:
        _attempt(core, db, actor, attempt_id, project_id, execution_id, step_id,
                 fencing_token, expected_revision, "UNCERTAIN")
        db.execute("""INSERT INTO AIReconciliationRecord VALUES(?,?,?,?,?,?,?)""",
                   (review_id, attempt_id, fencing_token, actor, decision.value,
                    evidence_ref, now))
        phase = "FAILED" if decision is ReviewDecision.MARK_FAILED else "UNCERTAIN"
        updated = db.execute("""UPDATE AIAttemptRecord SET phase=?,revision=revision+1,
            updated_at=? WHERE attempt_id=? AND phase='UNCERTAIN'
            AND fencing_token=? AND revision=?""",
            (phase, now, attempt_id, fencing_token, expected_revision))
        if updated.rowcount != 1:
            raise RecoveryRejected("Concurrent review")
        core._audit(db, actor, "AI_ATTEMPT_RECONCILE", project_id,
                    dict(review_id=review_id, attempt_id=attempt_id,
                         decision=decision.value, evidence_ref=evidence_ref,
                         fencing_token=fencing_token, expected_revision=expected_revision), now)
