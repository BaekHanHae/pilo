"""Minimal schema-2 fixtures for scope-boundary checks."""
import sqlite3
import unittest

from pilo_core.ai_scope import ScopeMismatch, validate_ai_scope


class AIScopeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
        CREATE TABLE Execution(execution_id TEXT, project_id TEXT, scope_type TEXT);
        CREATE TABLE ExecutionStep(execution_id TEXT, step_id TEXT);
        CREATE TABLE Checkpoint(checkpoint_id TEXT, project_id TEXT);
        CREATE TABLE ApprovalRequest(approval_id TEXT, execution_id TEXT,
            status TEXT, expires_at TEXT, action TEXT, resource_type TEXT,
            resource_id TEXT, resource_hash TEXT,
            approval_context_hash TEXT, policy_version_ref TEXT);
        CREATE TABLE ApprovalGrant(approval_id TEXT, project_id TEXT, revoked_at TEXT);
        INSERT INTO Execution VALUES ('e','p','PROJECT');
        INSERT INTO ExecutionStep VALUES ('e','s');
        INSERT INTO Checkpoint VALUES ('c','p');
        INSERT INTO ApprovalRequest VALUES ('a','e','APPROVED',NULL,
            'ai.execute','step','s','sha256:abc','ctx:abc','policy:v1');
        INSERT INTO ApprovalGrant VALUES ('a','p',NULL);
        """)
        self.args = dict(project_id="p", execution_id="e", step_id="s",
                         approval_id="a", checkpoint_id="c", side_effecting=True,
                         expected_action="ai.execute", expected_resource_type="step",
                         expected_resource_id="s", expected_resource_hash="sha256:abc",
                         expected_context_hash="ctx:abc",
                         expected_policy_version="policy:v1")

    def tearDown(self):
        self.db.close()

    def validate(self, **changes):
        return validate_ai_scope(self.db, **(self.args | changes))

    def test_valid_scoped_attempt(self):
        self.assertIsNone(self.validate())

    def test_cross_project_execution(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(project_id="other")

    def test_cross_execution_step(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(step_id="other")

    def test_cross_project_checkpoint(self):
        self.db.execute("UPDATE Checkpoint SET project_id='other'")
        with self.assertRaises(ScopeMismatch):
            self.validate()

    def test_missing_approval(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(approval_id=None)

    def test_revoked_approval(self):
        self.db.execute("UPDATE ApprovalGrant SET revoked_at='t'")
        with self.assertRaises(ScopeMismatch):
            self.validate()

    def test_unapproved_request(self):
        self.db.execute("UPDATE ApprovalRequest SET status='PENDING'")
        with self.assertRaises(ScopeMismatch):
            self.validate()

    def test_expired_request(self):
        self.db.execute("UPDATE ApprovalRequest SET expires_at='2000-01-01T00:00:00.000Z'")
        with self.assertRaises(ScopeMismatch):
            self.validate()

    def test_wrong_action(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(expected_action='other')

    def test_wrong_resource(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(expected_resource_id='other')

    def test_wrong_hash(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(expected_resource_hash='sha256:other')

    def test_missing_binding(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(expected_action=None)

    def test_wrong_context_hash(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(expected_context_hash='ctx:other')

    def test_wrong_policy_version(self):
        with self.assertRaises(ScopeMismatch):
            self.validate(expected_policy_version='policy:other')

    def test_read_only_without_approval(self):
        self.assertIsNone(self.validate(
            side_effecting=False, approval_id=None, checkpoint_id=None
        ))


if __name__ == "__main__":
    unittest.main()
