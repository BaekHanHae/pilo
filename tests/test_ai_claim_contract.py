"""Static safety checks for the dormant schema-3 claim implementation."""
import inspect
import unittest

from pilo_core.ai_claim import claim_ai_attempt


class AIClaimContractTests(unittest.TestCase):
    def test_claim_uses_core_write_transaction(self):
        source = inspect.getsource(claim_ai_attempt)
        self.assertIn("core.connection(write=True)", source)

    def test_claim_checks_core_permission(self):
        source = inspect.getsource(claim_ai_attempt)
        self.assertIn('core._authorize(db, actor, "ai.run"', source)

    def test_claim_has_revision_and_fence_compare_and_swap(self):
        source = inspect.getsource(claim_ai_attempt)
        self.assertIn("revision=? AND fencing_token=?", source)

    def test_claim_does_not_spawn_process(self):
        source = inspect.getsource(claim_ai_attempt)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("os.system", source)


if __name__ == "__main__":
    unittest.main()
