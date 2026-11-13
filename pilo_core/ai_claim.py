"""Atomic AI attempt claim using the candidate schema-3 table.

This code is dormant until a reviewed schema-3 migration is activated.
Core.connection(write=True) owns BEGIN IMMEDIATE, validation and commit.
"""
from __future__ import annotations

from .ai_core_gate import AIBinding
from .ai_execution_policy import AIExecutionPolicy, AIExecutionRequest, validate_admission
from .ai_scope import validate_ai_scope


class ClaimRejected(RuntimeError):
    """An AI attempt cannot be claimed safely."""


def claim_ai_attempt(
    core,
    *,
    actor: str,
    request: AIExecutionRequest,
    policy: AIExecutionPolicy,
    binding: AIBinding | None,
    expected_revision: int,
    now: str,
    attempt_id: str,
) -> int:
    """Claim an existing PENDING attempt, returning the new fencing token.

    Never launches a CLI. Authorization, scope, CAS and Core audit happen
    in one Core write transaction. Schema-3 migration and end-to-end
    verification are required before production use.
    """
    validate_admission(request, policy)
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ClaimRejected("Missing attempt ID")
    if type(expected_revision) is not int or expected_revision < 0:
        raise ClaimRejected("Invalid expected revision")
    if not isinstance(now, str) or not now.strip():
        raise ClaimRejected("Missing timestamp")
    side_effecting = request.effect_class.value != "READ_ONLY"
    if side_effecting and binding is None:
        raise ClaimRejected("Missing immutable approval binding")
    with core.connection(write=True) as db:
        core._authorize(db, actor, "ai.run", request.project_id)
        validate_ai_scope(
            db,
            project_id=request.project_id,
            execution_id=request.execution_id,
            step_id=request.step_id,
            approval_id=request.approval_ref,
            checkpoint_id=request.checkpoint_ref,
            side_effecting=side_effecting,
            expected_action=binding.action if binding else None,
            expected_resource_type=binding.resource_type if binding else None,
            expected_resource_id=binding.resource_id if binding else None,
            expected_resource_hash=binding.resource_hash if binding else None,
            expected_context_hash=binding.context_hash if binding else None,
            expected_policy_version=binding.policy_version if binding else None,
        )
        row = db.execute(
            """SELECT project_id,execution_id,step_id,adapter_id,effect_class,
                      approval_id,checkpoint_id,phase,fencing_token,revision
               FROM AIAttemptRecord WHERE attempt_id=?""",
            (attempt_id,),
        ).fetchone()
        if row is None:
            raise ClaimRejected("Attempt not found")
        project, execution, step, adapter, effect, approval, checkpoint, phase, fence, revision = row
        if (project, execution, step, adapter, effect, approval, checkpoint) != (
            request.project_id, request.execution_id, request.step_id,
            request.adapter_id, request.effect_class.value,
            request.approval_ref, request.checkpoint_ref,
        ):
            raise ClaimRejected("Immutable attempt binding mismatch")
        if phase != "PENDING" or revision != expected_revision:
            raise ClaimRejected("Attempt already claimed or stale revision")
        new_fence = fence + 1
        updated = db.execute(
            """UPDATE AIAttemptRecord
               SET phase='RUNNING',fencing_token=?,revision=revision+1,
                   updated_at=?
               WHERE attempt_id=? AND phase='PENDING'
                 AND revision=? AND fencing_token=?""",
            (new_fence, now, attempt_id,
             expected_revision, fence),
        )
        if updated.rowcount != 1:
            raise ClaimRejected("Concurrent claim detected")
        core._audit(db, actor, "AI_ATTEMPT_CLAIM", request.project_id,
                    {"attempt_id": attempt_id, "execution_id": request.execution_id,
                     "step_id": request.step_id, "fencing_token": new_fence}, now)
        return new_fence
