import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from pilo_core.bootstrap import initialize
from pilo_core.setup import add_project
from pilo_core.workspace import Workspace

class DistributionTests(unittest.TestCase):
    def test_fresh_setup_reader_and_disabled_indexer(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'state';source=root/'source';source.mkdir()
            (source/'guide.md').write_text('Sample checkpoint recovery evidence')
            initialize(state);config=state/'database_config.json'
            result=add_project(config,'sample','Sample',source)
            c=Workspace(config);self.assertIn('checkpoint',c.retrieve('pilo-reader',result['project_id'],'checkpoint')['content'])
            self.assertEqual(c.config['mcp_allow_writes'],False)
            with c.connection() as db:
                self.assertEqual(db.execute("SELECT count(*) FROM Principal WHERE principal_key LIKE 'setup-indexer:%' AND status='ACTIVE'").fetchone()[0],0)
                permissions=[r[0] for r in db.execute("SELECT p.permission_key FROM PrincipalRole pr JOIN RolePermission rp USING(role_id) JOIN Permission p USING(permission_id) WHERE pr.principal_id='pilo-reader'")]
            self.assertEqual(set(permissions),{'project.read','context.read'})
    def test_cli_first_run_and_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);state=root/'state';source=root/'source';source.mkdir()
            (source/'readme.md').write_text('PILO searchable sample context')
            def cli(*args):
                r=subprocess.run([sys.executable,'-m','pilo_core',*map(str,args)],text=True,capture_output=True,timeout=20,cwd=Path(__file__).resolve().parents[1])
                self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
            self.assertEqual(cli('init','--directory',state)['status'],'ok')
            cli('--config',state/'database_config.json','add-project','--key','sample','--name','Sample','--root',source)
            self.assertEqual(len(cli('--config',state/'database_config.json','list')['projects']),1)
            self.assertIn('searchable',cli('--config',state/'database_config.json','search','--project','sample','--query','searchable')['content'])
            repeated=subprocess.run([sys.executable,'-m','pilo_core','init','--directory',str(state)],text=True,capture_output=True,cwd=Path(__file__).resolve().parents[1])
            self.assertNotEqual(repeated.returncode,0)
    def test_packaged_migrations_match_applied_sources(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('0001_initial_schema.sql','0002_workspace.sql'):
            self.assertEqual((root/'pilo_core/sql'/name).read_bytes(),(root/'database/migrations'/name).read_bytes())
