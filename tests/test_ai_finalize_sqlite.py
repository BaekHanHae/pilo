"""Evidence integration with real Core, Git, SQLite, audit and content storage."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ai_candidate_support import install
from pilo_core import AccessDenied, ConfigurationError
from pilo_core.core import canonical
from pilo_core.operator import provision
from pilo_core.ai_finalize import finalize_ai_attempt, FinalizeRejected
from pilo_core.ai_provenance import register_ai_evidence, core_store, ProvenanceRejected


class FinalizeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.core, self.project, self.other = install(self.root)
        self.repo = self.root / 'repo'; self.repo.mkdir()
        self.git('init', '-q'); self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.repo / 'file').write_text('original')
        self.git('add', 'file'); self.git('commit', '-qm', 'Initial')
        self.commit = self.git('rev-parse', 'HEAD').strip()
        manifest = canonical(dict(project_id=self.project, git_commit=self.commit)).encode()
        ref = core_store(self.core).put(manifest)
        provision(self.core, 'executor', ['ai.run', 'ai.evidence'], self.project)
        with self.core.connection(write=True) as db:
            db.execute('UPDATE Project SET root_path=? WHERE project_id=?', (str(self.repo), self.project))
            db.execute("INSERT INTO Checkpoint VALUES('c',?,?,?,?,'system','t')",
                       (self.project, ref, ref, self.commit))
            db.execute("INSERT INTO CheckpointSeal VALUES('c')")
            db.execute("UPDATE AIAttemptRecord SET effect_class='READ_ONLY',checkpoint_id='c'")
        self.kw = dict(actor='executor', attempt_id='a', project_id=self.project,
            execution_id='e', step_id='s', fencing_token=4, expected_revision=1, now='t2')
        self.evidence, self.digest = self.register()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout

    def register(self, **updates):
        return register_ai_evidence(self.core, **(self.kw | dict(content=b'observed output') | updates))

    def finalize(self, **updates):
        finalize_ai_attempt(self.core, **(self.kw | dict(result_phase='COMPLETED',
            evidence_ref=self.evidence, evidence_sha256=self.digest) | updates))

    def state(self):
        with self.core.connection() as db:
            return db.execute('SELECT phase,revision FROM AIAttemptRecord').fetchone()

    def test_success_and_duplicate(self):
        self.finalize(); self.assertEqual(self.state(), ('COMPLETED', 2))
        with self.assertRaises(FinalizeRejected): self.finalize()
        self.core.health()

    def test_stale_fence_revision_and_identity(self):
        for change in (dict(fencing_token=3), dict(expected_revision=0), dict(step_id='other')):
            with self.assertRaises(FinalizeRejected): self.finalize(**change)

    def test_cross_project_reuse_denied(self):
        with self.assertRaises(AccessDenied): self.finalize(project_id=self.other)
        with self.core.connection(write=True) as db:
            db.execute("""INSERT INTO AIAttemptRecord SELECT 'b',project_id,execution_id,
                step_id,adapter_id,effect_class,phase,fencing_token,approval_id,
                checkpoint_id,input_digest,evidence_ref,created_at,updated_at,revision
                FROM AIAttemptRecord WHERE attempt_id='a'""")
        with self.assertRaises(ProvenanceRejected): self.finalize(attempt_id='b')

    def test_caller_store_denied(self):
        with self.assertRaises(FinalizeRejected): self.finalize(content_store=core_store(self.core))

    def test_substituted_or_missing_cas(self):
        path = core_store(self.core).root / self.digest
        path.write_bytes(b'substituted')
        with self.assertRaises(ConfigurationError): self.finalize()
        path.unlink()
        with self.assertRaises(ConfigurationError): self.finalize()
        self.assertEqual(self.state(), ('RUNNING', 1))

    def test_evidence_is_immutable(self):
        import sqlite3
        with self.core.connection(write=True) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE AIEvidenceRecord SET attempt_id=attempt_id')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM AIEvidenceRecord')

    def test_changed_untracked_and_ignored_worktree(self):
        for name in ('file', 'untracked'):
            path = self.repo / name; original = path.read_bytes() if path.exists() else None
            path.write_text('changed')
            with self.assertRaises(ProvenanceRejected): self.finalize()
            if original is None: path.unlink()
            else: path.write_bytes(original)
        (self.repo / '.git/info/exclude').write_text('ignored\n')
        (self.repo / 'ignored').write_text('unknown')
        with self.assertRaises(ProvenanceRejected): self.finalize()

    def test_assume_unchanged_refused(self):
        self.git('update-index', '--assume-unchanged', 'file')
        (self.repo / 'file').write_text('hidden change')
        with self.assertRaises(ProvenanceRejected): self.finalize()

    def test_changed_or_missing_git_object(self):
        self.git('commit', '--allow-empty', '-qm', 'Changed HEAD')
        with self.assertRaises(ProvenanceRejected): self.finalize()
        self.git('reset', '--soft', self.commit)
        obj = self.repo / '.git/objects' / self.commit[:2] / self.commit[2:]
        obj.unlink()
        with self.assertRaises(ProvenanceRejected): self.finalize()

    def test_git_timeout(self):
        with patch('pilo_core.ai_provenance.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('git', 5)):
            with self.assertRaises(ProvenanceRejected): self.finalize()
        self.assertEqual(self.state(), ('RUNNING', 1))

    def test_transactional_substitution_is_checked(self):
        original = self.core._authorize
        def substitute(db, *args):
            original(db, *args)
            (core_store(self.core).root / self.digest).write_bytes(b'race')
        with patch.object(self.core, '_authorize', side_effect=substitute):
            with self.assertRaises(ConfigurationError): self.finalize()

    def test_audit_failure_rolls_back(self):
        with patch.object(self.core, '_audit', side_effect=RuntimeError('disk')):
            with self.assertRaises(RuntimeError): self.finalize()
        self.assertEqual(self.state(), ('RUNNING', 1))

    def test_external_effects_are_never_proved_by_text(self):
        with self.core.connection(write=True) as db:
            db.execute("UPDATE AIAttemptRecord SET effect_class='EXTERNAL'")
        with self.assertRaises(ProvenanceRejected): self.register()
        with self.assertRaises(FinalizeRejected): self.finalize()
