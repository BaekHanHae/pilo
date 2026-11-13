"""Pure review gate for uncertain AI attempts; not an authorization system."""
from dataclasses import dataclass
from enum import Enum


class ReviewDecision(str, Enum):
    KEEP_BLOCKED = "KEEP_BLOCKED"
    MARK_FAILED = "MARK_FAILED"
    MARK_COMPLETED = "MARK_COMPLETED"


class ReviewDenied(ValueError):
    """Review evidence or identity is insufficient."""


@dataclass(frozen=True)
class ReconciliationRequest:
    attempt_id: str
    expected_fence: int
    current_fence: int
    current_phase: str
    reviewer_id: str
    evidence_ref: str
    decision: ReviewDecision


def validate_reconciliation(request: ReconciliationRequest) -> None:
    """Check structural evidence; Core must verify reviewer's authority and CAS."""
    if request.current_phase != "UNCERTAIN":
        raise ReviewDenied("Only uncertain attempts can be reconciled")
    if (type(request.expected_fence) is not int
            or type(request.current_fence) is not int
            or request.expected_fence <= 0
            or request.expected_fence != request.current_fence):
        raise ReviewDenied("Stale or invalid fencing token")
    if not isinstance(request.decision, ReviewDecision):
        raise ReviewDenied("Unknown decision")
    for value in (request.attempt_id, request.reviewer_id, request.evidence_ref):
        if not isinstance(value, str) or not value.strip():
            raise ReviewDenied("Missing identity or evidence")
    if request.decision is ReviewDecision.MARK_COMPLETED:
        raise ReviewDenied("Completion cannot be inferred from reconciliation alone")
