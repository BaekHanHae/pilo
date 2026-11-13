"""Unit tests for AI attempt state invariants."""
import unittest

from pilo_core.ai_attempt_state import (
    AIAttempt, AttemptPhase, TransitionDenied, cancel_pending,
    finish_attempt, interrupt_attempt, retry_permitted, start_attempt,
)


class AIAttemptStateTests(unittest.TestCase):
    def setUp(self):
        self.pending = AIAttempt("attempt")
        self.running = start_attempt(self.pending, 1)

    def test_initial_state(self):
        self.assertTrue(retry_permitted(self.pending))

    def test_start_increments_fence(self):
        self.assertEqual(self.running.fencing_token, 1)

    def test_duplicate_start_rejected(self):
        with self.assertRaises(TransitionDenied):
            start_attempt(self.running, 2)

    def test_stale_fence_rejected(self):
        with self.assertRaises(TransitionDenied):
            finish_attempt(self.running, 2, effects_known=True, evidence_ref="e")

    def test_success_requires_evidence(self):
        with self.assertRaises(TransitionDenied):
            finish_attempt(self.running, 1, effects_known=True, success=True)

    def test_success_records_evidence(self):
        done = finish_attempt(self.running, 1, effects_known=True,
                              success=True, evidence_ref="cas:abc")
        self.assertEqual(done.phase, AttemptPhase.COMPLETED)
        self.assertEqual(done.evidence_ref, "cas:abc")

    def test_known_failure_is_terminal(self):
        failed = finish_attempt(self.running, 1, effects_known=True,
                                evidence_ref="cas:failure")
        self.assertEqual(failed.phase, AttemptPhase.FAILED)
        self.assertFalse(retry_permitted(failed))

    def test_unknown_effects_are_uncertain(self):
        uncertain = finish_attempt(self.running, 1)
        self.assertEqual(uncertain.phase, AttemptPhase.UNCERTAIN)
        self.assertFalse(retry_permitted(uncertain))

    def test_timeout_is_uncertain(self):
        self.assertEqual(interrupt_attempt(self.running, 1).phase,
                         AttemptPhase.UNCERTAIN)

    def test_uncertain_cannot_finish(self):
        uncertain = interrupt_attempt(self.running, 1)
        with self.assertRaises(TransitionDenied):
            finish_attempt(uncertain, 1, effects_known=True, evidence_ref="e")

    def test_cancel_pending_only(self):
        self.assertEqual(cancel_pending(self.pending).phase, AttemptPhase.CANCELLED)
        with self.assertRaises(TransitionDenied):
            cancel_pending(self.running)

    def test_reject_boolean_fence(self):
        with self.assertRaises(TransitionDenied):
            start_attempt(self.pending, True)


if __name__ == "__main__":
    unittest.main()
