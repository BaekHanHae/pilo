"""Core-owned authorization gate for a proposed AI execution.

Read-only preflight: never spawn a process, grant an approval, or persist
an attempt. The final claim must repeat all checks in one write transaction.
"""
from __future__ import annotations

from dataclasses import dataclass

from .ai_execution_policy import (
    AIExecutionPolicy,
    AIExecutionRequest,
    validate_admission,
)
from .ai_scope import validate_ai_scope


@dataclass(frozen=True)
class AIBinding:
    action: str
    resource_type: str
    resource_id: str
    resource_hash: str
    context_hash: str
    policy_version: str


def preflight_ai_execution(
    core,
    actor: str,
    request: AIExecutionRequest,
    policy: AIExecutionPolicy,
    binding: AIBinding | None = None,
) -> None:
    """Validate Core permission and scope, without claiming execution.

    A caller MUST NOT interpret successful preflight as process authorization.
    """
    validate_admission(request, policy)
    side_effecting = request.effect_class.value != "READ_ONLY"
    if side_effecting and binding is None:
        raise PermissionError("Side-effecting AI execution requires exact binding")
    with core.connection() as db:
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
