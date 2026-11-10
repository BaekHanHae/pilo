import unittest
from pilo_core.ai_reconciliation import (
    ReconciliationRequest, ReviewDecision, ReviewDenied, validate_reconciliation,
)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.request = ReconciliationRequest(
            "attempt", 3, 3, "UNCERTAIN", "reviewer", "cas:proof",
            ReviewDecision.MARK_FAILED,
        )

    def check_denied(self, **updates):
        from dataclasses import replace
        with self.assertRaises(ReviewDenied):
            validate_reconciliation(replace(self.request, **updates))

    def test_valid_failure_review(self):
        self.assertIsNone(validate_reconciliation(self.request))

    def test_wrong_phase(self):
        self.check_denied(current_phase="RUNNING")

    def test_stale_fence(self):
        self.check_denied(current_fence=4)

    def test_boolean_fence(self):
        self.check_denied(expected_fence=True, current_fence=True)

    def test_missing_reviewer(self):
        self.check_denied(reviewer_id=" ")

    def test_missing_evidence(self):
        self.check_denied(evidence_ref="")

    def test_unknown_decision(self):
        self.check_denied(decision="MARK_FAILED")

    def test_completion_not_accepted(self):
        self.check_denied(decision=ReviewDecision.MARK_COMPLETED)

    def test_keep_blocked(self):
        from dataclasses import replace
        self.assertIsNone(validate_reconciliation(
            replace(self.request, decision=ReviewDecision.KEEP_BLOCKED)
        ))


if __name__ == "__main__":
    unittest.main()
