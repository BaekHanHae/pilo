"""Read-only scope checks for AI attempts against PILO Core schema 2.

These checks are a prerequisite, not authorization. The calling Core
transaction must independently enforce permissions, immutable bindings,
lease fencing and audit before any AI process is spawned.
"""
from __future__ import annotations

import sqlite3


class ScopeMismatch(PermissionError):
    """The proposed AI attempt crosses a project or approval boundary."""


def validate_ai_scope(
    db: sqlite3.Connection,
    *,
    project_id: str,
    execution_id: str,
    step_id: str,
    approval_id: str | None,
    checkpoint_id: str | None,
    side_effecting: bool,
    expected_action: str | None = None,
    expected_resource_type: str | None = None,
    expected_resource_id: str | None = None,
    expected_resource_hash: str | None = None,
) -> None:
    """Fail closed on missing, revoked, cross-project or unapproved scope."""
    values = (project_id, execution_id, step_id)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ScopeMismatch("Missing project/execution/step identity")

    execution = db.execute(
        "SELECT project_id, scope_type FROM Execution WHERE execution_id = ?",
        (execution_id,),
    ).fetchone()
    if execution != (project_id, "PROJECT"):
        raise ScopeMismatch("Execution does not belong to project")

    step = db.execute(
        "SELECT 1 FROM ExecutionStep WHERE execution_id = ? AND step_id = ?",
        (execution_id, step_id),
    ).fetchone()
    if step is None:
        raise ScopeMismatch("Step does not belong to execution")

    if side_effecting and (not approval_id or not checkpoint_id):
        raise ScopeMismatch("Side effects require approval and checkpoint")

    if checkpoint_id is not None:
        checkpoint = db.execute(
            "SELECT 1 FROM Checkpoint WHERE checkpoint_id = ? AND project_id = ?",
            (checkpoint_id, project_id),
        ).fetchone()
        if checkpoint is None:
            raise ScopeMismatch("Checkpoint does not belong to project")

    if side_effecting and any(
        not isinstance(value, str) or not value.strip()
        for value in (expected_action, expected_resource_type, expected_resource_id,
                      expected_resource_hash)
    ):
        raise ScopeMismatch("Side effects require exact action/resource/hash binding")

    if approval_id is not None:
        approval = db.execute(
            """SELECT 1
               FROM ApprovalRequest AS r
               JOIN ApprovalGrant AS g ON g.approval_id = r.approval_id
               WHERE r.approval_id = ?
                 AND r.execution_id = ?
                 AND r.status = 'APPROVED'
                 AND g.project_id = ?
                 AND g.revoked_at IS NULL
                 AND r.action = ?
                 AND r.resource_type = ?
                 AND r.resource_id = ?
                 AND r.resource_hash = ?
                 AND (r.expires_at IS NULL OR r.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ','now'))""",
            (approval_id, execution_id, project_id, expected_action,
             expected_resource_type, expected_resource_id, expected_resource_hash),
        ).fetchone()
        if approval is None:
            raise ScopeMismatch("Approval is missing, expired, revoked or out of scope")
