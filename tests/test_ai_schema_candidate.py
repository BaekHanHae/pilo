"""Structural tests for the schema-3 candidate; no production migration."""
import sqlite3
import unittest
from pathlib import Path


SQL = (Path(__file__).resolve().parents[1] /
       "pilo_core" / "sql" / "0003_ai_attempt_candidate.sql").read_text()


class Schema3CandidateTests(unittest.TestCase):
    def test_candidate_is_additive(self):
        self.assertIn("CREATE TABLE AIAttemptRecord", SQL)
        self.assertIn("CREATE TABLE AIReconciliationRecord", SQL)
        self.assertNotIn("ALTER TABLE StepAttempt", SQL)
        self.assertNotIn("DROP TABLE", SQL)

    def test_rejects_invalid_phases_and_effect_classes(self):
        # A minimal existing-schema stub validates CHECK constraints independently
        # of migration and Core authorization.
        db = sqlite3.connect(":memory:")
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
        CREATE TABLE Project(project_id TEXT PRIMARY KEY);
        CREATE TABLE Execution(execution_id TEXT PRIMARY KEY);
        CREATE TABLE ExecutionStep(execution_id TEXT,step_id TEXT,
            PRIMARY KEY(execution_id,step_id));
        CREATE TABLE Principal(principal_id TEXT PRIMARY KEY);
        CREATE TABLE ApprovalRequest(approval_id TEXT PRIMARY KEY);
        CREATE TABLE Checkpoint(checkpoint_id TEXT PRIMARY KEY);
        INSERT INTO Project VALUES ('p');
        INSERT INTO Execution VALUES ('e');
        INSERT INTO ExecutionStep VALUES ('e','s');
        INSERT INTO Principal VALUES ('reviewer');
        """)
        db.executescript(SQL)
        base = ("p", "e", "s", "adapter", "READ_ONLY", "PENDING", 0,
                None, None, "a" * 64, None, "t", "t", 0)
        columns = ("project_id,execution_id,step_id,adapter_id,effect_class,"
                   "phase,fencing_token,approval_id,checkpoint_id,input_digest,"
                   "evidence_ref,created_at,updated_at,revision")
        def insert(attempt_id, values):
            db.execute(
                f"INSERT INTO AIAttemptRecord(attempt_id,{columns}) "
                "VALUES (" + ",".join("?" for _ in range(15)) + ")",
                (attempt_id, *values),
            )
        insert("valid", base)
        with self.assertRaises(sqlite3.IntegrityError):
            insert("bad-phase", base[:5] + ("UNKNOWN",) + base[6:])
        with self.assertRaises(sqlite3.IntegrityError):
            insert("bad-effect", base[:4] + ("UNKNOWN",) + base[5:])
        with self.assertRaises(sqlite3.IntegrityError):
            insert("bad-fence", base[:6] + (1,) + base[7:])
        with self.assertRaises(sqlite3.IntegrityError):
            insert("bad-hash", base[:9] + ("not-a-digest",) + base[10:])
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute("INSERT INTO AIReconciliationRecord VALUES "
                       "('r','valid',1,'reviewer','MARK_COMPLETED','proof','t')")
        db.close()


if __name__ == "__main__":
    unittest.main()
