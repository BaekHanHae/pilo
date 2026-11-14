"""SQLite transaction tests for dormant AI attempt finalization."""
import contextlib
import sqlite3
import tempfile
from pilo_core.storage import ContentStore
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

    def _verify_audit(self, db):
        pass

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
            CREATE TABLE AIAttemptRecord (
                attempt_id TEXT PRIMARY KEY NOT NULL,
                project_id TEXT NOT NULL REFERENCES Project(project_id) ON DELETE RESTRICT,
                execution_id TEXT NOT NULL REFERENCES Execution(execution_id) ON DELETE RESTRICT,
                step_id TEXT NOT NULL,
                adapter_id TEXT NOT NULL CHECK(length(trim(adapter_id)) > 0),
                effect_class TEXT NOT NULL CHECK(effect_class IN ('READ_ONLY','WORKTREE_WRITE','EXTERNAL')),
                phase TEXT NOT NULL CHECK(phase IN ('PENDING','RUNNING','COMPLETED','FAILED','UNCERTAIN','CANCELLED')),
                fencing_token INTEGER NOT NULL DEFAULT 0 CHECK(fencing_token >= 0),
                approval_id TEXT REFERENCES ApprovalRequest(approval_id) ON DELETE RESTRICT,
                checkpoint_id TEXT REFERENCES Checkpoint(checkpoint_id) ON DELETE RESTRICT,
                input_digest TEXT NOT NULL CHECK(length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'),
                evidence_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                UNIQUE(execution_id, attempt_id),
                FOREIGN KEY(execution_id, step_id) REFERENCES ExecutionStep(execution_id, step_id) ON DELETE RESTRICT,
                CHECK (
                    (phase = 'PENDING' AND fencing_token = 0)
                    OR (phase <> 'PENDING' AND fencing_token > 0)
                )
            ) STRICT;
            INSERT INTO Execution VALUES('e','p','PROJECT');
            INSERT INTO ExecutionStep VALUES('e','s');
            INSERT INTO AIAttemptRecord VALUES
                ('a','p','e','s','mock','READ_ONLY','RUNNING',4,NULL,NULL,
                 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                 NULL,'t','t',1);
        """)
        self.core = FakeCore(self.db)
        self.tempdir = tempfile.TemporaryDirectory()
        self.store = ContentStore(self.tempdir.name)
        self.digest = self.store.put(b"verified result evidence")
        self.kw = dict(
            actor="operator", attempt_id="a", project_id="p",
            execution_id="e", step_id="s", fencing_token=4,
            expected_revision=1, result_phase="COMPLETED",
            evidence_ref=self.digest, evidence_sha256=self.digest, now="t2",
            content_store=self.store,
        )

    def tearDown(self):
        self.db.close()
        self.tempdir.cleanup()

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

    def test_missing_core_store_rejected(self):
        with self.assertRaises(FinalizeRejected):
            self.run_finalize(content_store=None)

    def test_tampered_evidence_rejected(self):
        with self.assertRaises(FinalizeRejected):
            self.run_finalize(evidence_sha256="a" * 64)

    def test_invalid_digest(self):
        with self.assertRaises(FinalizeRejected):
            self.run_finalize(evidence_sha256="bad")

    def test_unrecognized_effect_class_fails_closed(self):
        # Inject invalid persisted data to test Core's rejection independently
        # of the production schema's CHECK constraint on effect_class.
        self.db.execute("PRAGMA ignore_check_constraints=ON")
        self.db.execute("UPDATE AIAttemptRecord SET effect_class='INVALID'")
        self.db.execute("PRAGMA ignore_check_constraints=OFF")
        with self.assertRaises(FinalizeRejected):
            self.run_finalize()
        self.assertEqual(self.phase(), ("RUNNING", 1))

    def test_side_effect_requires_binding(self):
        self.db.execute("UPDATE AIAttemptRecord SET effect_class='WORKTREE_WRITE'")
        with self.assertRaises(FinalizeRejected):
            self.run_finalize()
        self.assertEqual(self.phase(), ("RUNNING", 1))

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
