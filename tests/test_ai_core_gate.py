"""Preflight gate checks Core permission without executing a worker."""
import contextlib
import sqlite3
import unittest
from unittest.mock import Mock

from pilo_core.ai_core_gate import AIBinding, preflight_ai_execution
from pilo_core.ai_execution_policy import (
    AIExecutionPolicy, AIExecutionRequest, EffectClass,
)


class CoreGateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE Execution(execution_id TEXT,project_id TEXT,scope_type TEXT);
            CREATE TABLE ExecutionStep(execution_id TEXT,step_id TEXT);
            CREATE TABLE Checkpoint(checkpoint_id TEXT,project_id TEXT);
            CREATE TABLE ApprovalRequest(approval_id TEXT,execution_id TEXT,
                status TEXT,expires_at TEXT,action TEXT,resource_type TEXT,
                resource_id TEXT,resource_hash TEXT,approval_context_hash TEXT,
                policy_version_ref TEXT);
            CREATE TABLE ApprovalGrant(approval_id TEXT,project_id TEXT,revoked_at TEXT);
            INSERT INTO Execution VALUES('e','p','PROJECT');
            INSERT INTO ExecutionStep VALUES('e','s');
            INSERT INTO Checkpoint VALUES('c','p');
            INSERT INTO ApprovalRequest VALUES
                ('a','e','APPROVED',NULL,'ai.execute','step','s','h','ctx','v1');
            INSERT INTO ApprovalGrant VALUES('a','p',NULL);
        """)
        self.core = Mock()
        self.core.connection.side_effect = lambda: contextlib.nullcontext(self.db)
        self.request = AIExecutionRequest("p", "e", "s", "mock", EffectClass.READ_ONLY)
        self.policy = AIExecutionPolicy(True, frozenset({"mock"}))

    def tearDown(self):
        self.db.close()

    def test_read_only_checks_ai_permission(self):
        preflight_ai_execution(self.core, "user", self.request, self.policy)
        self.core._authorize.assert_called_once_with(
            self.db, "user", "ai.run", "p"
        )

    def test_permission_denial_is_fail_closed(self):
        self.core._authorize.side_effect = PermissionError("denied")
        with self.assertRaises(PermissionError):
            preflight_ai_execution(self.core, "user", self.request, self.policy)

    def test_side_effects_require_binding(self):
        request = AIExecutionRequest(
            "p", "e", "s", "mock", EffectClass.WORKTREE_WRITE, "a", "c"
        )
        policy = AIExecutionPolicy(True, frozenset({"mock"}), True)
        with self.assertRaises(PermissionError):
            preflight_ai_execution(self.core, "user", request, policy)

    def test_side_effects_with_exact_binding(self):
        request = AIExecutionRequest(
            "p", "e", "s", "mock", EffectClass.WORKTREE_WRITE, "a", "c"
        )
        policy = AIExecutionPolicy(True, frozenset({"mock"}), True)
        binding = AIBinding("ai.execute", "step", "s", "h", "ctx", "v1")
        preflight_ai_execution(self.core, "user", request, policy, binding)

    def test_revoked_approval_rejected(self):
        self.db.execute("UPDATE ApprovalGrant SET revoked_at='now'")
        request = AIExecutionRequest(
            "p", "e", "s", "mock", EffectClass.WORKTREE_WRITE, "a", "c"
        )
        policy = AIExecutionPolicy(True, frozenset({"mock"}), True)
        binding = AIBinding("ai.execute", "step", "s", "h", "ctx", "v1")
        with self.assertRaises(PermissionError):
            preflight_ai_execution(self.core, "user", request, policy, binding)


if __name__ == "__main__":
    unittest.main()
