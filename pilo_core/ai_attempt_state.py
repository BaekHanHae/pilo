"""Pure AI attempt state transitions; no process execution or database writes.

The Core integration must persist each transition atomically and validate
authorization, approvals and lease ownership independently.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class AttemptPhase(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    CANCELLED = "CANCELLED"


class TransitionDenied(ValueError):
    """Attempt transition violates state or fencing invariants."""


@dataclass(frozen=True)
class AIAttempt:
    attempt_id: str
    phase: AttemptPhase = AttemptPhase.PENDING
    fencing_token: int = 0
    evidence_ref: str | None = None


def start_attempt(attempt: AIAttempt, fencing_token: int) -> AIAttempt:
    """Start a new attempt only from PENDING with a strictly newer fence."""
    if attempt.phase is not AttemptPhase.PENDING:
        raise TransitionDenied("Only pending attempts may start")
    if not isinstance(fencing_token, int) or isinstance(fencing_token, bool):
        raise TransitionDenied("Fencing token must be an integer")
    if fencing_token <= attempt.fencing_token:
        raise TransitionDenied("Fencing token must advance")
    return replace(attempt, phase=AttemptPhase.RUNNING, fencing_token=fencing_token)


def finish_attempt(
    attempt: AIAttempt,
    fencing_token: int,
    *,
    success: bool = False,
    effects_known: bool = False,
    evidence_ref: str | None = None,
) -> AIAttempt:
    """Unknown effects are UNCERTAIN, never an automatic retry candidate."""
    if attempt.phase is not AttemptPhase.RUNNING:
        raise TransitionDenied("Attempt is not running")
    if fencing_token != attempt.fencing_token:
        raise TransitionDenied("Stale fencing token")
    if not effects_known:
        return replace(attempt, phase=AttemptPhase.UNCERTAIN)
    if not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise TransitionDenied("Known effects require evidence")
    phase = AttemptPhase.COMPLETED if success else AttemptPhase.FAILED
    return replace(attempt, phase=phase, evidence_ref=evidence_ref)


def interrupt_attempt(attempt: AIAttempt, fencing_token: int) -> AIAttempt:
    """Timeout, lease expiry or cancellation during execution is uncertain."""
    if attempt.phase is not AttemptPhase.RUNNING:
        raise TransitionDenied("Attempt is not running")
    if fencing_token != attempt.fencing_token:
        raise TransitionDenied("Stale fencing token")
    return replace(attempt, phase=AttemptPhase.UNCERTAIN)


def cancel_pending(attempt: AIAttempt) -> AIAttempt:
    if attempt.phase is not AttemptPhase.PENDING:
        raise TransitionDenied("Running or terminal attempts cannot be silently cancelled")
    return replace(attempt, phase=AttemptPhase.CANCELLED)


def retry_permitted(attempt: AIAttempt) -> bool:
    """Only unstarted pending attempts qualify; no automatic external retry."""
    return attempt.phase is AttemptPhase.PENDING
