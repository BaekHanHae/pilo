"""Unit tests for the isolated AI execution admission contract."""
import unittest

from pilo_core.ai_execution_policy import (
    AdmissionDenied,
    AIExecutionPolicy,
    AIExecutionRequest,
    EffectClass,
    validate_admission,
)


class AIAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.request = AIExecutionRequest(
            "project", "execution", "step", "mock",
            EffectClass.READ_ONLY,
        )
        self.policy = AIExecutionPolicy(
            enabled=True, permitted_adapters=frozenset({"mock"})
        )

    def test_default_is_disabled(self):
        with self.assertRaises(AdmissionDenied):
            validate_admission(self.request, AIExecutionPolicy())

    def test_allowlisted_read_only(self):
        self.assertIsNone(validate_admission(self.request, self.policy))

    def test_unknown_adapter_rejected(self):
        req = AIExecutionRequest("p", "e", "s", "unknown", EffectClass.READ_ONLY)
        with self.assertRaises(AdmissionDenied):
            validate_admission(req, self.policy)

    def test_missing_identity_rejected(self):
        req = AIExecutionRequest(" ", "e", "s", "mock", EffectClass.READ_ONLY)
        with self.assertRaises(AdmissionDenied):
            validate_admission(req, self.policy)

    def test_unknown_effect_rejected(self):
        req = AIExecutionRequest("p", "e", "s", "mock", "READ_ONLY")
        with self.assertRaises(AdmissionDenied):
            validate_admission(req, self.policy)

    def test_worktree_write_requires_references_and_policy(self):
        req = AIExecutionRequest("p", "e", "s", "mock", EffectClass.WORKTREE_WRITE)
        with self.assertRaises(AdmissionDenied):
            validate_admission(req, self.policy)
        req = AIExecutionRequest(
            "p", "e", "s", "mock", EffectClass.WORKTREE_WRITE, "approval", "checkpoint"
        )
        with self.assertRaises(AdmissionDenied):
            validate_admission(req, self.policy)
        allowed = AIExecutionPolicy(
            enabled=True, permitted_adapters=frozenset({"mock"}),
            allow_worktree_write=True,
        )
        self.assertIsNone(validate_admission(req, allowed))

    def test_external_effects_separately_disabled(self):
        req = AIExecutionRequest(
            "p", "e", "s", "mock", EffectClass.EXTERNAL, "approval", "checkpoint"
        )
        policy = AIExecutionPolicy(
            enabled=True, permitted_adapters=frozenset({"mock"}),
            allow_worktree_write=True,
        )
        with self.assertRaises(AdmissionDenied):
            validate_admission(req, policy)


if __name__ == "__main__":
    unittest.main()
