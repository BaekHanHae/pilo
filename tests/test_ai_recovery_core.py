"""Recovery against actual Core transactions, RBAC, audit and SQLite FKs."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ai_candidate_support import install, CandidateCore
from pilo_core import AccessDenied
from pilo_core.ai_recovery import mark_ai_uncertain, reconcile_ai_attempt, RecoveryRejected
from pilo_core.ai_reconciliation import ReviewDecision


class RecoveryCoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.core, self.project, self.other = install(Path(temp.name))
        self.kw = dict(actor='reviewer', attempt_id='a', project_id=self.project,
                       execution_id='e', step_id='s', fencing_token=4,
                       expected_revision=1, now='t2')

    def state(self):
        with self.core.connection() as db:
            return db.execute('SELECT phase,revision FROM AIAttemptRecord').fetchone()

    def uncertain(self, **changes):
        mark_ai_uncertain(self.core, **(self.kw | dict(reason='Process effects unknown') | changes))

    def review(self, **changes):
        reconcile_ai_attempt(self.core, **(self.kw | dict(expected_revision=2,
            review_id='r', evidence_ref='operator observation',
            decision=ReviewDecision.KEEP_BLOCKED) | changes))

    def test_recovery_without_execution_authority_or_approval(self):
        # The recovery principal lacks ai.run and there is no valid execution approval.
        with self.core.connection() as db:
            with self.assertRaises(AccessDenied):
                self.core._authorize(db, 'reviewer', 'ai.run', self.project)
        self.uncertain()
        self.assertEqual(self.state(), ('UNCERTAIN', 2))
        self.core = CandidateCore(self.core.config_path)
        self.assertEqual(self.state(), ('UNCERTAIN', 2))
        self.core.health()

    def test_revoked_approval_during_execution(self):
        with self.core.connection(write=True) as db:
            db.execute("UPDATE ApprovalGrant SET revoked_at='2026-01-02' WHERE approval_id='approval'")
        self.uncertain()
        self.assertEqual(self.state(), ('UNCERTAIN', 2))

    def test_stale_duplicate_and_identity_rejected(self):
        for update in (dict(fencing_token=3), dict(expected_revision=0),
                       dict(execution_id='other'), dict(step_id='other')):
            with self.assertRaises(RecoveryRejected): self.uncertain(**update)
        self.uncertain()
        with self.assertRaises(RecoveryRejected): self.uncertain()

    def test_project_and_authority_isolation(self):
        for update in (dict(project_id=self.other), dict(actor='system')):
            with self.assertRaises(AccessDenied): self.uncertain(**update)
        self.assertEqual(self.state(), ('RUNNING', 1))

    def test_audit_failure_rolls_back_transition(self):
        with patch.object(self.core, '_audit', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError): self.uncertain()
        self.assertEqual(self.state(), ('RUNNING', 1))

    def test_review_is_fenced_and_never_retries(self):
        self.uncertain(); self.review()
        self.assertEqual(self.state(), ('UNCERTAIN', 3))
        with self.assertRaises(RecoveryRejected): self.review()
        self.review(review_id='r2', expected_revision=3, decision=ReviewDecision.MARK_FAILED)
        self.assertEqual(self.state(), ('FAILED', 4))
        with self.core.connection(write=True) as db:
            import sqlite3
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM AIReconciliationRecord")
        self.core.health()

    def test_review_audit_failure_rolls_back_record_and_revision(self):
        self.uncertain()
        with patch.object(self.core, '_audit', side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError): self.review()
        self.assertEqual(self.state(), ('UNCERTAIN', 2))
        with self.core.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM AIReconciliationRecord').fetchone(), (0,))
