"""Dormant Core-owned AI attempt finalization transaction.

Requires reviewed schema-3 migration. No CLI execution is performed.
"""
from __future__ import annotations

import re

from .ai_scope import validate_ai_scope
from .ai_evidence import verify_evidence, EvidenceRejected
from .storage import ContentStore


class FinalizeRejected(RuntimeError):
    """An AI attempt cannot be finalized safely."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def finalize_ai_attempt(
    core,
    *,
    actor: str,
    attempt_id: str,
    project_id: str,
    execution_id: str,
    step_id: str,
    fencing_token: int,
    expected_revision: int,
    result_phase: str,
    evidence_ref: str | None,
    evidence_sha256: str | None,
    now: str,
    content_store: ContentStore | None = None,
) -> None:
    """Finalize with fence, revision, identity, permission and audit checks.

    Evidence is read directly from a Core-owned ContentStore, never from an
    adapter-provided reader or boolean assertion. Workspace effects and
    provenance still require separate verification. UNCERTAIN is
    intentionally permitted without evidence and blocks automatic retries.
    """
    if not all(isinstance(v, str) and v.strip() for v in (
        actor, attempt_id, project_id, execution_id, step_id, now
    )):
        raise FinalizeRejected("Missing required identity")
    if type(fencing_token) is not int or fencing_token <= 0:
        raise FinalizeRejected("Invalid fencing token")
    if type(expected_revision) is not int or expected_revision < 0:
        raise FinalizeRejected("Invalid revision")
    if result_phase not in ("COMPLETED", "FAILED", "UNCERTAIN"):
        raise FinalizeRejected("Unsupported result phase")
    if result_phase != "UNCERTAIN" and (
        not isinstance(evidence_ref, str) or not evidence_ref.strip()
        or not isinstance(evidence_sha256, str)
        or _SHA256.fullmatch(evidence_sha256) is None
    ):
        raise FinalizeRejected("Verified result requires evidence reference and digest")

    if result_phase != "UNCERTAIN":
        if not isinstance(content_store, ContentStore):
            raise FinalizeRejected("Core ContentStore required for finalization")
        if evidence_ref != evidence_sha256:
            raise FinalizeRejected("Evidence reference must be the CAS digest")
        try:
            verify_evidence(evidence_ref, evidence_sha256, content_store.get)
        except (EvidenceRejected, OSError, ValueError) as exc:
            raise FinalizeRejected("CAS evidence verification failed") from exc

    with core.connection(write=True) as db:
        core._authorize(db, actor, "ai.run", project_id)
        validate_ai_scope(
            db, project_id=project_id, execution_id=execution_id,
            step_id=step_id, approval_id=None, checkpoint_id=None,
            side_effecting=False,
        )
        row = db.execute(
            """SELECT project_id,execution_id,step_id,phase,fencing_token,revision
               FROM AIAttemptRecord WHERE attempt_id=?""",
            (attempt_id,),
        ).fetchone()
        if row is None or row[:3] != (project_id, execution_id, step_id):
            raise FinalizeRejected("Attempt identity mismatch")
        if row[3:] != ("RUNNING", fencing_token, expected_revision):
            raise FinalizeRejected("Stale fence, revision or attempt state")
        updated = db.execute(
            """UPDATE AIAttemptRecord SET phase=?, evidence_ref=?,
                      revision=revision+1,updated_at=?
               WHERE attempt_id=? AND phase='RUNNING'
                 AND fencing_token=? AND revision=?""",
            (result_phase, evidence_ref, now, attempt_id,
             fencing_token, expected_revision),
        )
        if updated.rowcount != 1:
            raise FinalizeRejected("Concurrent finalization")
        core._audit(db, actor, "AI_ATTEMPT_FINALIZE", project_id, {
            "attempt_id": attempt_id,
            "phase": result_phase,
            "fencing_token": fencing_token,
            "evidence_ref": evidence_ref,
            "evidence_sha256": evidence_sha256,
        }, now)
