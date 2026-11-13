"""Fail-closed admission contract for proposed PILO-Skills AI CLI execution.

This module is deliberately not wired into the existing CODE scheduler.
A successful admission is NOT permission to spawn a process: the Core must
independently verify durable approval, scope, audit, and fencing.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    WORKTREE_WRITE = "WORKTREE_WRITE"
    EXTERNAL = "EXTERNAL"


class AdmissionDenied(PermissionError):
    """The requested AI execution does not meet the admission contract."""


@dataclass(frozen=True)
class AIExecutionRequest:
    project_id: str
    execution_id: str
    step_id: str
    adapter_id: str
    effect_class: EffectClass
    approval_ref: str | None = None
    checkpoint_ref: str | None = None


@dataclass(frozen=True)
class AIExecutionPolicy:
    enabled: bool = False
    permitted_adapters: frozenset[str] = frozenset()
    allow_worktree_write: bool = False
    allow_external_effects: bool = False


def validate_admission(
    request: AIExecutionRequest,
    policy: AIExecutionPolicy,
) -> None:
    """Validate structural admission only; never authorize process execution.

    Callers must additionally check Core principal permissions, approval
    authenticity and scope, immutable execution binding, and lease fencing.
    """
    if not policy.enabled:
        raise AdmissionDenied("AI execution is disabled")
    for value in (
        request.project_id,
        request.execution_id,
        request.step_id,
        request.adapter_id,
    ):
        if not isinstance(value, str) or not value.strip():
            raise AdmissionDenied("Missing execution identity")
    if request.adapter_id not in policy.permitted_adapters:
        raise AdmissionDenied("Adapter is not allowlisted")
    if not isinstance(request.effect_class, EffectClass):
        raise AdmissionDenied("Unknown effect class")
    if request.effect_class is EffectClass.READ_ONLY:
        return
    if not request.approval_ref or not request.approval_ref.strip():
        raise AdmissionDenied("Side-effecting execution requires approval reference")
    if not request.checkpoint_ref or not request.checkpoint_ref.strip():
        raise AdmissionDenied("Side-effecting execution requires checkpoint reference")
    if request.effect_class is EffectClass.WORKTREE_WRITE:
        if not policy.allow_worktree_write:
            raise AdmissionDenied("Worktree writes are disabled")
        return
    if not policy.allow_external_effects:
        raise AdmissionDenied("External effects are disabled")
