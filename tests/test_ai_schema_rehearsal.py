"""Real migration-copy rehearsal, never activation of the source installation."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pilo_core import Core, AccessDenied, ConfigurationError
from pilo_core.bootstrap import initialize
from pilo_core.ai_schema_rehearsal import rehearse, checksum
from pilo_core.operator import provision
from ai_candidate_support import install


class RehearsalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        initialize(self.root / 'instance')
        self.config = self.root / 'instance/database_config.json'
        self.target = self.root / 'rehearsal'

    def test_clean_install_and_2_to_3_copy_preserve_source(self):
        core = Core(self.config)
        before = checksum(core.path), checksum(self.config)
        result = rehearse(self.config, self.target)
        self.assertEqual(before, (checksum(core.path), checksum(self.config)))
        self.assertFalse(result['ai_execution_enabled'])
        self.assertEqual(core.health()['schema_version'], 2)
        with closing(sqlite3.connect(self.target / 'schema3.candidate.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (3,))
            self.assertEqual(db.execute("SELECT count(*) FROM RolePermission rp JOIN Permission p USING(permission_id) WHERE p.permission_key LIKE 'ai.%'").fetchone(), (0,))
        with self.assertRaises(FileExistsError): rehearse(self.config, self.target)

    def test_restart_after_commit_recovers_report_without_reapplying(self):
        with patch('pilo_core.ai_schema_rehearsal._publish', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError): rehearse(self.config, self.target)
        digest = checksum(self.target / 'schema3.candidate.sqlite3')
        (self.target / 'report.staged.json').write_text('untrusted partial data')
        result = rehearse(self.config, self.target, resume=True)
        self.assertEqual(digest, result['candidate_database_sha256'])
        self.assertEqual(json.loads((self.target / 'report.json').read_text()), result)

    def test_backup_tamper_and_history_tamper_fail_closed(self):
        rehearse(self.config, self.target)
        backup = self.target / 'schema2.backup.sqlite3'
        with backup.open('ab') as out: out.write(b'tamper')
        with self.assertRaises(ConfigurationError): rehearse(self.config, self.target, resume=True)

    def test_candidate_checksum_history_tamper(self):
        rehearse(self.config, self.target)
        with closing(sqlite3.connect(self.target / 'schema3.candidate.sqlite3')) as db:
            # Migration history is protected by the original immutable trigger.
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE SchemaMigration SET checksum='bad' WHERE version=3")
            db.execute('PRAGMA user_version=2')
            db.commit()
        with self.assertRaises(ConfigurationError): rehearse(self.config, self.target, resume=True)

    def test_real_rbac_default_deny_and_project_provisioning(self):
        core, project, other = install(self.root / 'candidate')
        for permission in ('ai.run', 'ai.evidence', 'ai.reconcile'):
            with core.connection() as db:
                with self.assertRaises(AccessDenied): core._authorize(db, 'system', permission, project)
        provision(core, 'runner', ['ai.run'], project)
        with core.connection() as db:
            core._authorize(db, 'runner', 'ai.run', project)
            with self.assertRaises(AccessDenied): core._authorize(db, 'runner', 'ai.run', other)
            with self.assertRaises(AccessDenied): core._authorize(db, 'runner', 'ai.reconcile', project)

    def test_composite_binding_and_identity_immutability(self):
        core, project, other = install(self.root / 'candidate')
        with core.connection(write=True) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""INSERT INTO AIAttemptRecord VALUES('cross',?,'e','s',
                    'test','READ_ONLY','PENDING',0,NULL,NULL,?,NULL,'t','t',0)""", (other, 'a'*64))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE AIAttemptRecord SET project_id=?", (other,))
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE AIAttemptRecord SET phase='PENDING',fencing_token=0,revision=2")
        core.health()

    def test_ddl_failure_rolls_back_copy_and_preserves_source(self):
        core = Core(self.config)
        before = checksum(core.path), checksum(self.config)
        with patch('pilo_core.ai_schema_rehearsal.statements',
                   return_value=iter(('CREATE TABLE partial(value TEXT);', 'INVALID SQL;'))):
            with self.assertRaises(sqlite3.OperationalError): rehearse(self.config, self.target)
        self.assertEqual(before, (checksum(core.path), checksum(self.config)))
        with closing(sqlite3.connect(self.target / 'schema3.candidate.sqlite3')) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone(), (2,))
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_schema WHERE name='partial'").fetchone())
        with self.assertRaises(ConfigurationError): rehearse(self.config, self.target, resume=True)

    def test_changed_candidate_source_rejected_on_resume(self):
        from pilo_core.ai_schema_rehearsal import CANDIDATE
        rehearse(self.config, self.target)
        changed = self.root / 'modified.sql'
        changed.write_text(CANDIDATE.read_text() + '\n-- changed proposal\n')
        with patch('pilo_core.ai_schema_rehearsal.CANDIDATE', changed):
            with self.assertRaises(ConfigurationError): rehearse(self.config, self.target, resume=True)
