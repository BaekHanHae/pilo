"""SQLite transaction tests for dormant AI attempt finalization."""
import contextlib
import sqlite3
import unittest

from pilo_core.ai_finalize import FinalizeRejected, finalize_ai_attempt


class FakeCore:
    def __init__(self, db):
        self.db = db
        self.audit_fails = False

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
        if actor != "operator":
            raise PermissionError("denied")

    def _audit(self, db, actor, action, resource, details, now):
        if self.audit_fails:
            raise RuntimeError("audit failed")


class FinalizeTests(unittest.TestCase):
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
            CREATE TABLE AIAttemptRecord(attempt_id TEXT PRIMARY KEY,
                project_id TEXT,execution_id TEXT,step_id TEXT,phase TEXT,
                fencing_token INTEGER,revision INTEGER,evidence_ref TEXT,
                updated_at TEXT);
            INSERT INTO Execution VALUES('e','p','PROJECT');
            INSERT INTO ExecutionStep VALUES('e','s');
            INSERT INTO AIAttemptRecord VALUES
                ('a','p','e','s','RUNNING',4,1,NULL,'t');
        """)
        self.core = FakeCore(self.db)
        self.kw = dict(
            actor="operator", attempt_id="a", project_id="p",
            execution_id="e", step_id="s", fencing_token=4,
            expected_revision=1, result_phase="COMPLETED",
            evidence_ref="cas:proof", evidence_sha256="a"*64, now="t2",
            evidence_verified=True,
        )

    def tearDown(self):
        self.db.close()

    def run_finalize(self, **updates):
        finalize_ai_attempt(self.core, **(self.kw | updates))

    def phase(self):
        return self.db.execute(
            "SELECT phase,revision FROM AIAttemptRecord"
        ).fetchone()

    def test_success(self):
        self.run_finalize()
        self.assertEqual(self.phase(), ("COMPLETED", 2))

    def test_duplicate_finalization_rejected(self):
        self.run_finalize()
        with self.assertRaises(FinalizeRejected):
            self.run_finalize()

    def test_stale_fence(self):
        with self.assertRaises(FinalizeRejected):
            self.run_finalize(fencing_token=3)

    def test_stale_revision(self):
        with self.assertRaises(FinalizeRejected):
            self.run_finalize(expected_revision=0)

    def test_uncertain_without_evidence(self):
        self.run_finalize(result_phase="UNCERTAIN",
                          evidence_ref=None, evidence_sha256=None)
        self.assertEqual(self.phase(), ("UNCERTAIN", 2))

    def test_unverified_evidence_rejected(self):
        with self.assertRaises(FinalizeRejected):
            self.run_finalize(evidence_verified=False)

    def test_invalid_digest(self):
        with self.assertRaises(FinalizeRejected):
            self.run_finalize(evidence_sha256="bad")

    def test_permission_denial(self):
        with self.assertRaises(PermissionError):
            self.run_finalize(actor="unauthorized")
        self.assertEqual(self.phase(), ("RUNNING", 1))

    def test_audit_failure_rolls_back(self):
        self.core.audit_fails = True
        with self.assertRaises(RuntimeError):
            self.run_finalize()
        self.assertEqual(self.phase(), ("RUNNING", 1))


if __name__ == "__main__":
    unittest.main()
