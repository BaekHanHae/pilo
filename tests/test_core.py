from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pilo_core import Core, AccessDenied, ConfigurationError
ROOT = Path(__file__).resolve().parents[1]

@contextmanager
def closing_connection(path):
    db=sqlite3.connect(path)
    try:
        with db:yield db
    finally:db.close()

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = self.root / 'test.sqlite3'
        from pilo_core.bootstrap import initialize
        initialize(self.root/'instance',upgrade_workspace=False)
        self.config=self.root/'instance/database_config.json'
        self.db=self.root/'instance/data/pilo.sqlite3';self.core=Core(self.config)

    def grant(self,permission,project=None):
        with closing_connection(self.db) as db:
            db.execute('INSERT INTO Permission VALUES (?,?,?,?)',(permission,permission,'Fixture only','2026-11-10'))
            role=db.execute("SELECT role_id FROM PrincipalRole WHERE principal_id='system'").fetchone()[0]
            if project:
                role='scoped'; db.execute('INSERT INTO Role VALUES (?,?,?,?,?)',(role,role,role,None,'2026-11-10'))
                db.execute("INSERT INTO PrincipalRole VALUES ('scoped','system',?,'PROJECT',?,'2026-11-10',NULL)",(role,project))
            db.execute('INSERT INTO RolePermission VALUES (?,?)',(role,permission))
    def create(self,key='test'): return self.core.create_project('system',key,'Test',self.root)
    def test_health(self): self.assertEqual(self.core.health()['strict_tables'],37)
    def test_default_deny(self):
        for actor in ('system','missing'):
            with self.assertRaises(AccessDenied): self.core.list_projects(actor)
            with self.assertRaises(AccessDenied): self.core.create_project(actor,'x','X',self.root)
        self.assertEqual(self.core.health()['audit_events'],1)
    def test_atomic_project_and_space(self):
        self.grant('project.create'); result=self.create()
        with closing_connection(self.db) as db:
            self.assertEqual(db.execute('SELECT project_id FROM KnowledgeSpace WHERE space_id=?',(result['space_id'],)).fetchone()[0],result['project_id'])
        self.assertEqual(self.core.health()['audit_events'],2)
    def test_duplicate_rollback(self):
        self.grant('project.create'); self.create()
        with self.assertRaises(sqlite3.IntegrityError): self.create()
        self.assertEqual(self.core.health()['audit_events'],2)
    def test_audit_failure_rollback(self):
        self.grant('project.create')
        with patch.object(self.core,'_audit',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError): self.create()
        with closing_connection(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Project').fetchone()[0],0)
            self.assertEqual(db.execute("SELECT count(*) FROM KnowledgeSpace WHERE space_type='PROJECT'").fetchone()[0],0)
    def test_scope_isolation(self):
        self.grant('project.create'); first=self.create(); second=self.create('second'); self.grant('project.read',first['project_id'])
        self.assertEqual(self.core.get_project('system',first['project_id'])['project_key'],'test')
        with self.assertRaises(AccessDenied): self.core.get_project('system',second['project_id'])
        with self.assertRaises(AccessDenied): self.core.list_projects('system')
    def test_disabled_actor(self):
        self.grant('project.create')
        with closing_connection(self.db) as db: db.execute("UPDATE Principal SET status='DISABLED' WHERE principal_id='system'")
        with self.assertRaises(AccessDenied): self.create()
    def test_policy_fail_closed(self):
        self.grant('project.create')
        with closing_connection(self.db) as db: db.execute("INSERT INTO AccessPolicy VALUES ('p','p','REQUIRE_APPROVAL','REQUIRE_APPROVAL','{}','ACTIVE',0,'system','2026-11-10','2026-11-10')")
        with self.assertRaises(AccessDenied): self.create()
    def test_schema_drift(self):
        with closing_connection(self.db) as db: db.execute('CREATE TABLE sqliteXpayload(value TEXT)')
        with self.assertRaises(ConfigurationError): self.core.health()
    def test_version_refusal(self):
        with closing_connection(self.db) as db: db.execute('PRAGMA user_version=2')
        with self.assertRaises(ConfigurationError): self.core.health()
    def test_checksum_refusal(self):
        config=json.loads(self.config.read_text()); config['schema_sha256']='0'*64; self.config.write_text(json.dumps(config))
        with self.assertRaises(ConfigurationError): Core(self.config)
    def test_backup(self):
        self.grant('project.create'); self.create(); target=self.root/'backup.sqlite3'; self.core.backup(target)
        with closing_connection(target) as db: self.assertEqual(db.execute('SELECT count(*) FROM Project').fetchone()[0],1)
        before=target.read_bytes()
        with self.assertRaises(FileExistsError): self.core.backup(target)
        self.assertEqual(before,target.read_bytes())
    def test_missing_database_not_created(self):
        self.db.unlink()
        with self.assertRaises(sqlite3.OperationalError): self.core.health()
        self.assertFalse(self.db.exists())
    def test_readonly_and_pragmas(self):
        with self.core.connection() as db:
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA recursive_triggers').fetchone()[0],1)
            with self.assertRaises(sqlite3.OperationalError): db.execute("UPDATE Project SET name='no'")

if __name__=='__main__': unittest.main()
