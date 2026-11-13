"""SQLite transaction tests for the dormant AI claim path.

Uses a minimal schema-2-compatible fixture, not a migrated production DB.
"""
import contextlib
import sqlite3
import unittest

from pilo_core.ai_claim import ClaimRejected, claim_ai_attempt
from pilo_core.ai_execution_policy import (
    AIExecutionPolicy, AIExecutionRequest, EffectClass,
)


class FakeCore:
    def __init__(self, db, audit_fails=False):
        self.db = db
        self.audit_fails = audit_fails
        self.audit_calls = []

    @contextlib.contextmanager
    def connection(self, write=False):
        self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        try:
            yield self.db
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _authorize(self, db, actor, permission, project):
        if actor != "authorized" or permission != "ai.run" or project != "p":
            raise PermissionError("denied")

    def _audit(self, db, actor, action, resource, details, timestamp):
        if self.audit_fails:
            raise RuntimeError("audit failure")
        self.audit_calls.append((actor, action, details["fencing_token"]))


class AIClaimSQLiteTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.executescript("""
            CREATE TABLE Execution(execution_id TEXT,project_id TEXT,scope_type TEXT);
            CREATE TABLE ExecutionStep(execution_id TEXT,step_id TEXT);
            CREATE TABLE Checkpoint(checkpoint_id TEXT,project_id TEXT);
            CREATE TABLE ApprovalRequest(approval_id TEXT,execution_id TEXT,
                status TEXT,expires_at TEXT,action TEXT,resource_type TEXT,
                resource_id TEXT,resource_hash TEXT,approval_context_hash TEXT,
                policy_version_ref TEXT);
            CREATE TABLE ApprovalGrant(approval_id TEXT,project_id TEXT,revoked_at TEXT);
            CREATE TABLE AIAttemptRecord(
                attempt_id TEXT PRIMARY KEY,project_id TEXT,execution_id TEXT,
                step_id TEXT,adapter_id TEXT,effect_class TEXT,approval_id TEXT,
                checkpoint_id TEXT,phase TEXT,fencing_token INTEGER,
                revision INTEGER,updated_at TEXT);
            INSERT INTO Execution VALUES('e','p','PROJECT');
            INSERT INTO ExecutionStep VALUES('e','s');
            INSERT INTO AIAttemptRecord VALUES(
                'a1','p','e','s','mock','READ_ONLY',NULL,NULL,'PENDING',0,0,'t');
        """)
        self.core = FakeCore(self.db)
        self.request = AIExecutionRequest("p", "e", "s", "mock", EffectClass.READ_ONLY)
        self.policy = AIExecutionPolicy(True, frozenset({"mock"}))

    def tearDown(self):
        self.db.close()

    def claim(self, **changes):
        return claim_ai_attempt(
            self.core, actor=changes.get("actor", "authorized"),
            request=self.request, policy=self.policy, binding=None,
            expected_revision=changes.get("revision", 0),
            now="2026-01-01T00:00:00Z", attempt_id="a1",
        )

    def test_claim_advances_fence_and_revision(self):
        self.assertEqual(self.claim(), 1)
        self.assertEqual(self.db.execute(
            "SELECT phase,fencing_token,revision FROM AIAttemptRecord"
        ).fetchone(), ("RUNNING", 1, 1))
        self.assertEqual(len(self.core.audit_calls), 1)

    def test_duplicate_claim_rejected(self):
        self.claim()
        with self.assertRaises(ClaimRejected):
            self.claim()

    def test_stale_revision_rejected(self):
        with self.assertRaises(ClaimRejected):
            self.claim(revision=1)

    def test_permission_denial_rolls_back(self):
        with self.assertRaises(PermissionError):
            self.claim(actor="unauthorized")
        self.assertEqual(self.db.execute(
            "SELECT phase FROM AIAttemptRecord"
        ).fetchone()[0], "PENDING")

    def test_audit_failure_rolls_back_claim(self):
        self.core.audit_fails = True
        with self.assertRaises(RuntimeError):
            self.claim()
        self.assertEqual(self.db.execute(
            "SELECT phase,fencing_token,revision FROM AIAttemptRecord"
        ).fetchone(), ("PENDING", 0, 0))


if __name__ == "__main__":
    unittest.main()
